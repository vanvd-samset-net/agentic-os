"""Phase 2: worker + adapter shell/claude-code với agent giả (không gọi mô hình thật)."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from aos import config, db, secrets, store, worker
from aos.adapters import claude_code

PY = sys.executable
FAKE_CLAUDE = r'''
import json, os, sys
prompt = sys.stdin.read()
args = sys.argv[1:]
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "sleep":
    import time; time.sleep(60)
text = {"ok": "Đã làm xong.\nAOS_RESULT: done - site chạy", "blocked": "AOS_RESULT: blocked - cần tạo site trong Local",
        "error": "lỗi API"}[mode if mode in ("ok", "blocked", "error") else "ok"]
res = {"type": "result", "subtype": "success" if mode != "error" else "error_during_execution", "is_error": mode == "error",
       "result": text, "session_id": "sess-1", "num_turns": 3, "total_cost_usd": 0.42,
       "usage": {"input_tokens": 5, "output_tokens": 7, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 20},
       "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "git push"}}] if "--allowedTools" in args else []}
open(os.path.join(os.getcwd(), "argv.json"), "w", encoding="utf-8").write(json.dumps({"args": args, "prompt": prompt, "secret": os.environ.get("API_TOKEN"), "leak": os.environ.get("PARENT_ONLY")}))
print(json.dumps(res))
sys.exit(1 if mode == "error" else 0)
'''


class WorkerBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old_data, db.DATA = db.DATA, root / "data"
        self.old_secrets, secrets.SECRETS_DIR = secrets.SECRETS_DIR, root / "secrets"
        self.work = root / "agentwork"
        self.work.mkdir()
        (root / "fake_claude.py").write_text(FAKE_CLAUDE, encoding="utf-8")
        self.fake = str(root / "fake_claude.py")
        self.con = db.connect(root / "aos.db")
        store.ensure_org(self.con, "Công ty", "Sứ mệnh thử")
        store.add_project(self.con, "lop3d", "LỚP", "Xưởng in 3D")

    def tearDown(self):
        db.DATA, secrets.SECRETS_DIR = self.old_data, self.old_secrets
        self.con.close()
        self.tmp.cleanup()

    def agent(self, aid, adapter, **cfg):
        cfg = {"adapter": adapter, "workdir": str(self.work), **cfg}
        config.validate(aid, cfg)
        store.upsert_agent(self.con, aid, aid, adapter, config=cfg)

    def run_task(self, aid, title="việc", **kw):
        tid = store.add_task(self.con, "lop3d", title, agent_id=aid, **kw)
        res = worker.run_once(self.con, aid, "w1", self.tmp.name, heartbeat_every=1)
        return tid, res

    def last_run(self):
        return dict(self.con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone())


class ShellAdapterTest(WorkerBase):
    def test_success_goes_to_review_with_summary_and_prompt_context(self):
        self.agent("echo", "shell", shell={"command": [PY, "-c", "import sys; d=sys.stdin.read(); print('ctx' if 'Sứ mệnh thử' in d and 'Xưởng in 3D' in d else 'noctx'); print('AOS_RESULT: done - ổn')"]})
        tid, res = self.run_task("echo")
        self.assertEqual(res, (tid, "under_review"))
        self.assertIn("ctx", (Path(self.last_run()["log_dir"]) / "stdout.log").read_text(encoding="utf-8"))
        self.assertEqual(store.get_task(self.con, tid)["result_summary"], "ổn")

    def test_blocked_result_line(self):
        self.agent("echo", "shell", shell={"command": [PY, "-c", "print('AOS_RESULT: blocked - thiếu quyền Local')"]})
        tid, res = self.run_task("echo")
        task = store.get_task(self.con, tid)
        self.assertEqual((res[1], task["blocked_reason"]), ("blocked", "thiếu quyền Local"))

    def test_failure_retries_then_fails(self):
        self.agent("echo", "shell", shell={"command": [PY, "-c", "import sys; sys.exit(3)"]})
        tid, res = self.run_task("echo", max_attempts=2)
        self.assertEqual(res[1], "assigned")
        self.assertEqual(worker.run_once(self.con, "echo", "w1", self.tmp.name)[1], "failed")
        self.assertIsNone(worker.run_once(self.con, "echo", "w1", self.tmp.name))

    def test_timeout_kills_agent(self):
        self.agent("slow", "shell", timeout_s=2, shell={"command": [PY, "-c", "import time; time.sleep(60)"]})
        t0 = time.monotonic()
        tid, res = self.run_task("slow", max_attempts=1)
        self.assertLess(time.monotonic() - t0, 30)
        self.assertEqual((res[1], self.last_run()["status"]), ("failed", "timeout"))

    def test_cancel_during_run_stops_agent(self):
        self.agent("slow", "shell", shell={"command": [PY, "-c", "import time; time.sleep(60)"]})
        tid = store.add_task(self.con, "lop3d", "x", agent_id="slow")
        import threading
        def cancel_soon():
            time.sleep(2)
            con2 = db.connect(Path(self.tmp.name) / "aos.db")
            store.cancel(con2, tid, actor="human:van")
            con2.close()
        threading.Thread(target=cancel_soon).start()
        t0 = time.monotonic()
        res = worker.run_once(self.con, "slow", "w1", self.tmp.name, heartbeat_every=1)
        self.assertLess(time.monotonic() - t0, 30)
        self.assertEqual(res[1], "cancelled")
        self.assertEqual(self.last_run()["status"], "cancelled")

    def test_secrets_scoped_and_redacted(self):
        secrets.SECRETS_DIR.mkdir(parents=True)
        (secrets.SECRETS_DIR / "echo.env").write_text("API_TOKEN=sk-sieu-bi-mat-123\nOTHER=khong-duoc-cap\n", encoding="utf-8")
        os.environ["PARENT_ONLY"] = "bien-cua-nguoi-chay"
        try:
            self.agent("echo", "shell", secrets=["API_TOKEN"],
                       shell={"command": [PY, "-c", "import os; print(os.environ.get('API_TOKEN'), os.environ.get('OTHER'), os.environ.get('PARENT_ONLY'))"]})
            tid, res = self.run_task("echo")
        finally:
            del os.environ["PARENT_ONLY"]
        out = (Path(self.last_run()["log_dir"]) / "stdout.log").read_text(encoding="utf-8")
        self.assertEqual(out.split(), ["***", "None", "None"])
        audit = " ".join(r[0] for r in self.con.execute("SELECT data_json FROM audit_log"))
        self.assertNotIn("sk-sieu-bi-mat-123", audit + json.dumps(store.get_task(self.con, tid), ensure_ascii=False))

    def test_missing_secret_fails_run_without_starting_agent(self):
        self.agent("echo", "shell", secrets=["API_TOKEN"], shell={"command": [PY, "-c", "print('chạy')"]})
        tid, res = self.run_task("echo", max_attempts=1)
        self.assertEqual(res[1], "failed")
        self.assertIn("Thiếu bí mật", self.last_run()["error"])

    def test_handoff_contract(self):
        out = self.work / "projects" / "lop3d" / "output"
        out.mkdir(parents=True)
        (out / "handoff.json").write_text('{"status": "done"}', encoding="utf-8")
        old = time.time() - 3600
        os.utime(out / "handoff.json", (old, old))
        handoff = {"file": "projects/{project_slug}/output/handoff.json", "done": ["done"], "blocked": ["blocked"]}
        self.agent("wp", "shell", handoff=handoff, shell={"command": [PY, "-c", "print('AOS_RESULT: done - xong')"]})
        tid, res = self.run_task("wp", max_attempts=1)
        self.assertEqual(res[1], "failed", "handoff.json cũ không được tin")
        script = "import json; open('projects/lop3d/output/handoff.json','w').write(json.dumps({'status':'blocked','reason':'Q-001 chặn'}))"
        self.agent("wp", "shell", handoff=handoff, shell={"command": [PY, "-c", script]})
        tid, res = self.run_task("wp")
        self.assertEqual((res[1], store.get_task(self.con, tid)["blocked_reason"]), ("blocked", "Q-001 chặn"))


class ClaudeAdapterTest(WorkerBase):
    def cfg(self, **kw):
        return {"command": [PY, self.fake], "permission_mode": "dontAsk", "allowed_tools": ["Read", "Bash(git status *)"],
                "disallowed_tools": ["Bash(git push *)"], "max_turns": 50, **kw}

    def test_success_records_usage_cost_session_and_denials(self):
        self.agent("cc", "claude-code", claude=self.cfg(), env={"WP_AGENT_PROJECT": "{project_slug}"})
        tid, res = self.run_task("cc", title="Làm site LỚP")
        run = self.last_run()
        self.assertEqual(res[1], "under_review")
        self.assertEqual((run["input_tokens"], run["output_tokens"], run["cache_read_tokens"], run["cache_write_tokens"]),
                         (5, 7, 100, 20))
        self.assertEqual((run["cost_usd"], run["session_id"], run["num_turns"]), (0.42, "sess-1", 3))
        argv = json.loads((self.work / "argv.json").read_text(encoding="utf-8"))
        self.assertIn("Làm site LỚP", argv["prompt"])
        a = argv["args"]
        self.assertEqual(a[a.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(a[a.index("--allowedTools") + 1], "Read,Bash(git status *)")
        note = a[a.index("--append-system-prompt") + 1]
        self.assertIn("được phép: Read, Bash(git status *)", note)   # agent biết quyền của mình
        self.assertIn("lệnh đơn", note)
        self.assertTrue((Path(run["log_dir"]) / "permission_denials.json").exists())
        self.assertIn("bị từ chối quyền", store.get_task(self.con, tid)["result_summary"] or
                      self.con.execute("SELECT body FROM task_comments WHERE kind='agent'").fetchone()[0])

    def test_blocked_and_error(self):
        # Biến phải đi qua cấu hình env của agent: tiến trình agent không thừa hưởng môi trường của worker.
        self.agent("cc", "claude-code", claude=self.cfg(), env={"FAKE_MODE": "blocked"})
        tid, res = self.run_task("cc")
        self.assertEqual(res[1], "blocked")
        self.agent("cc", "claude-code", claude=self.cfg(), env={"FAKE_MODE": "error"})
        tid, res = self.run_task("cc", max_attempts=1)
        self.assertEqual(res[1], "failed")
        self.assertIn("error_during_execution", self.last_run()["error"])

    def test_bypass_permissions_is_rejected_by_config(self):
        for bad in ({"permission_mode": "bypassPermissions"}, {"extra_args": ["--dangerously-skip-permissions"]}):
            with self.assertRaises(config.ConfigError):
                config.validate("cc", {"adapter": "claude-code", "workdir": ".", "claude": self.cfg(**bad)})

    def test_usage_prefers_model_usage_when_present(self):
        u = claude_code.usage_from({"usage": {"input_tokens": 1}, "total_cost_usd": 1.5, "modelUsage": {
            "opus": {"inputTokens": 10, "outputTokens": 2, "cacheReadInputTokens": 30, "cacheCreationInputTokens": 4},
            "haiku": {"inputTokens": 5, "outputTokens": 1, "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0}}})
        self.assertEqual((u["input_tokens"], u["output_tokens"], u["cache_read_tokens"], u["cost_usd"]), (15, 3, 30, 1.5))


class WorktreeTest(WorkerBase):
    def test_worktree_per_task(self):
        if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
            self.skipTest("không có git")
        repo = self.work
        for c in (["init", "-q"], ["config", "user.email", "t@example.test"], ["config", "user.name", "t"],
                  ["commit", "-q", "--allow-empty", "-m", "init"]):
            subprocess.run(["git", "-C", str(repo), *c], check=True, capture_output=True)
        self.agent("wt", "shell", workspace="worktree", shell={"command": [PY, "-c", "import os; print(os.getcwd())"]})
        tid, res = self.run_task("wt")
        out = (Path(self.last_run()["log_dir"]) / "stdout.log").read_text(encoding="utf-8").strip()
        self.assertTrue(out.replace("\\", "/").endswith(f"worktrees/task-{tid}"))
        branches = subprocess.run(["git", "-C", str(repo), "branch", "--list", f"aos/task-{tid}"], capture_output=True, text=True).stdout
        self.assertIn(f"aos/task-{tid}", branches)


if __name__ == "__main__":
    unittest.main()
