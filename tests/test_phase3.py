"""Phase 3: nâng cấp CSDL v1 → v2, ngân sách (trước/trong/sau khi chạy), cổng công cụ, phê duyệt."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from aos import budgets, config, db, secrets, store, tools, worker

PY = sys.executable
FAKE = r'''
import json, os, sys
args = sys.argv[1:]
sys.stdin.read()
mode = os.environ.get("FAKE_MODE", "ok")
cost = float(os.environ.get("FAKE_COST", "0.5"))
open("argv.json", "w", encoding="utf-8").write(json.dumps(args))
res = {"type": "result", "subtype": "success", "is_error": False, "result": "AOS_RESULT: done - xong",
       "session_id": "s", "num_turns": 2, "total_cost_usd": cost,
       "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
       "permission_denials": []}
if mode == "budget":
    res.update(subtype="error_max_budget_usd", is_error=True, result=None)
if mode == "deny":
    res["permission_denials"] = [{"tool_name": "Bash", "tool_use_id": "t1", "tool_input": {"command": "git commit -m 'site'"}},
                                 {"tool_name": "Bash", "tool_use_id": "t2", "tool_input": {"command": "curl http://x"}}]
print(json.dumps(res))
'''


class P3Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old = (db.DATA, secrets.SECRETS_DIR)
        db.DATA, secrets.SECRETS_DIR = root / "data", root / "secrets"
        self.work = root / "work"
        self.work.mkdir()
        (root / "fake.py").write_text(FAKE, encoding="utf-8")
        self.fake = str(root / "fake.py")
        self.con = db.connect(root / "aos.db")
        store.ensure_org(self.con, "Công ty", "")
        store.add_project(self.con, "lop3d", "LỚP")
        store.add_project(self.con, "manga", "MANGA")

    def tearDown(self):
        db.DATA, secrets.SECRETS_DIR = self.old
        self.con.close()
        self.tmp.cleanup()

    def agent(self, aid="cc", mode="ok", cost="0.5", **extra):
        cfg = {"adapter": "claude-code", "workdir": str(self.work), "env": {"FAKE_MODE": mode, "FAKE_COST": cost},
               "claude": {"command": [PY, self.fake], "permission_mode": "dontAsk"},
               "tools": {"allowed": ["Read", "Edit"], "ask": ["Bash(git commit *)"], "off": ["Bash(git push *)"]}, **extra}
        config.validate(aid, cfg)
        store.upsert_agent(self.con, aid, aid, "claude-code", config=cfg, status=None)

    def run1(self, aid="cc"):
        return worker.run_once(self.con, aid, "w1", self.tmp.name)

    def argv(self):
        return json.loads((self.work / "argv.json").read_text(encoding="utf-8"))


class MigrationTest(unittest.TestCase):
    def test_v1_database_upgrades_keeping_tasks(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "old.db"
            raw = sqlite3.connect(path)
            raw.executescript("CREATE TABLE schema_version (version INTEGER NOT NULL);")
            for stmt in db.split_sql(db.SCHEMA[0]):
                raw.execute(stmt)
            raw.execute("INSERT INTO schema_version VALUES (1)")
            raw.execute("INSERT INTO organizations (name, created_at) VALUES ('c', 'x')")
            raw.execute("INSERT INTO projects (org_id, slug, name, created_at) VALUES (1, 'p', 'P', 'x')")
            raw.execute("INSERT INTO tasks (project_id, title, status, created_by, created_at, updated_at) "
                        "VALUES (1, 'việc cũ', 'backlog', 'h', 'x', 'x')")
            raw.execute("INSERT INTO task_comments (task_id, author, body, created_at) VALUES (1, 'h', 'ghi chú', 'x')")
            raw.commit()
            raw.close()
            con = db.connect(path)
            self.assertEqual(con.execute("SELECT version FROM schema_version").fetchone()[0], 2)
            self.assertEqual(con.execute("SELECT title FROM tasks WHERE id = 1").fetchone()[0], "việc cũ")
            con.execute("UPDATE tasks SET status = 'needs_approval' WHERE id = 1")  # CHECK mới nhận trạng thái mới
            self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(con.execute("SELECT COUNT(*) FROM task_comments").fetchone()[0], 1)
            con.close()


class BudgetTest(P3Base):
    def test_pre_run_block_then_approve_with_raise(self):
        self.agent()
        budgets.set_budget(self.con, "project", "lop3d", usd=0.8)
        t1 = store.add_task(self.con, "lop3d", "a", agent_id="cc")
        self.assertEqual(self.run1()[1], "under_review")                 # tiêu 0.5
        self.assertIn("--max-budget-usd", self.argv())                   # truyền phần còn lại cho CLI
        self.assertEqual(self.argv()[self.argv().index("--max-budget-usd") + 1], "0.8000")
        t2 = store.add_task(self.con, "lop3d", "b", agent_id="cc")
        self.assertEqual(self.run1()[1], "under_review")                 # còn 0.3 → vẫn chạy, tiêu thêm 0.5 → 1.0
        t3 = store.add_task(self.con, "lop3d", "c", agent_id="cc")
        self.assertEqual(self.run1(), (t3, "needs_approval"))            # đã vượt → không chạy agent
        task = store.get_task(self.con, t3)
        self.assertEqual(task["attempts"], 0, "bị chặn trước khi chạy không tính lượt")
        appr = store.list_approvals(self.con)
        self.assertEqual((len(appr), appr[0]["kind"]), (1, "budget"))
        with self.assertRaises(ValueError):
            store.decide(self.con, appr[0]["id"], True)                  # duyệt mà không nâng hạn mức → vẫn hết
        self.assertEqual(store.decide(self.con, appr[0]["id"], True, raise_usd=1.0), "assigned")
        self.assertEqual(self.run1(), (t3, "under_review"))
        self.assertEqual(store.get_task(self.con, t1)["status"], "under_review")
        self.assertEqual(store.get_task(self.con, t2)["status"], "under_review")

    def test_other_project_not_affected(self):
        self.agent()
        budgets.set_budget(self.con, "project", "lop3d", usd=0.1)
        store.add_task(self.con, "lop3d", "a", agent_id="cc")
        self.run1()
        t = store.add_task(self.con, "manga", "b", agent_id="cc")
        self.assertEqual(self.run1(), (t, "under_review"))

    def test_in_run_budget_stop_needs_approval(self):
        self.agent(mode="budget")
        budgets.set_budget(self.con, "task", "1", usd=2)
        t = store.add_task(self.con, "lop3d", "a", agent_id="cc")
        self.assertEqual(self.run1(), (t, "needs_approval"))
        self.assertEqual(store.list_approvals(self.con)[0]["kind"], "budget")
        self.assertEqual(store.decide(self.con, store.list_approvals(self.con)[0]["id"], False, note="dừng"), "failed")

    def test_warn_once_and_auto_pause_agent(self):
        self.agent(cost="0.45")
        budgets.set_budget(self.con, "agent", "cc", usd=1.0, warn=0.4)
        store.add_task(self.con, "lop3d", "a", agent_id="cc")
        self.run1()                                                      # 0.45 ≥ 40% → cảnh báo
        store.add_task(self.con, "manga", "b", agent_id="cc")
        self.run1()                                                      # 0.90 → không cảnh báo lại
        warns = self.con.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'budget.warn'").fetchone()[0]
        self.assertEqual(warns, 1)
        self.assertEqual(store.get_agent(self.con, "cc")["status"], "active")
        store.add_task(self.con, "lop3d", "c", agent_id="cc")
        self.run1()                                                      # 1.35 ≥ 100% → tự tạm dừng
        self.assertEqual(store.get_agent(self.con, "cc")["status"], "paused")
        self.agent(cost="0.45")                                          # nạp lại cấu hình không bật lại agent
        self.assertEqual(store.get_agent(self.con, "cc")["status"], "paused")
        store.add_task(self.con, "lop3d", "d", agent_id=None)
        self.assertIsNone(self.run1())
        store.resume_agent(self.con, "cc")
        self.assertEqual(store.get_agent(self.con, "cc")["status"], "active")

    def test_token_budget_and_month_period(self):
        self.agent()
        budgets.set_budget(self.con, "org", tokens=120, period="month")
        store.add_task(self.con, "lop3d", "a", agent_id="cc")
        self.run1()                                                      # 150 token
        s = budgets.list_all(self.con)[0]
        self.assertEqual((s["spent_tokens"], s["ratio"] >= 1), (150, True))
        t = store.add_task(self.con, "manga", "b", agent_id="cc")
        self.assertEqual(self.run1(), (t, "needs_approval"))


class ToolGateTest(P3Base):
    def test_ask_rule_denied_creates_approval_then_grant_is_used(self):
        self.agent(mode="deny")
        t = store.add_task(self.con, "lop3d", "a", agent_id="cc")
        self.assertEqual(self.run1(), (t, "needs_approval"))
        a = self.argv()
        self.assertEqual(a[a.index("--allowedTools") + 1], "Read,Edit")
        self.assertEqual(a[a.index("--disallowedTools") + 1], "Bash(git push *)")
        appr = store.list_approvals(self.con)[0]
        self.assertEqual((appr["kind"], appr["request"]["rules"]), ("tool", ["Bash(git commit *)"]))
        self.assertEqual(len(appr["request"]["calls"]), 1, "curl không thuộc nhóm ask: chỉ ghi, không xin duyệt")
        self.assertEqual(store.decide(self.con, appr["id"], True, note="được commit"), "assigned")
        self.assertEqual(store.grants(self.con, t), ["Bash(git commit *)"])
        self.agent(mode="ok")
        self.assertEqual(self.run1(), (t, "under_review"))
        a = self.argv()
        self.assertEqual(a[a.index("--allowedTools") + 1], "Read,Edit,Bash(git commit *)")

    def test_grant_is_per_task_and_deny_goes_to_review(self):
        self.agent(mode="deny")
        t1 = store.add_task(self.con, "lop3d", "a", agent_id="cc")
        self.run1()
        self.assertEqual(store.decide(self.con, store.list_approvals(self.con)[0]["id"], False, note="không cần commit"),
                         "under_review")
        self.agent(mode="ok")
        store.add_task(self.con, "manga", "b", agent_id="cc")
        self.run1()
        a = self.argv()
        self.assertNotIn("Bash(git commit *)", a[a.index("--allowedTools") + 1])
        self.assertEqual(store.grants(self.con, t1), [])

    def test_worker_cannot_decide(self):
        self.agent(mode="deny")
        store.add_task(self.con, "lop3d", "a", agent_id="cc")
        self.run1()
        from aos import states
        with self.assertRaises(states.TransitionError):
            store.decide(self.con, store.list_approvals(self.con)[0]["id"], True, actor="worker:w1")


class RuleMatchTest(unittest.TestCase):
    def test_rules(self):
        m = tools.rule_matches
        self.assertTrue(m("Bash(git commit *)", "Bash", {"command": "git commit -m x"}))
        self.assertTrue(m("Bash(git commit *)", "Bash", {"command": "git commit"}))
        self.assertFalse(m("Bash(git commit *)", "Bash", {"command": "git commitx"}))
        self.assertFalse(m("Bash(git commit *)", "Bash", {"command": "git push"}))
        self.assertTrue(m("Bash(git log:*)", "Bash", {"command": "git log --oneline"}))
        self.assertTrue(m("WebFetch", "WebFetch", {"url": "https://x"}))
        self.assertFalse(m("WebFetch", "Bash", {"command": "curl"}))

    def test_policy_backward_compatible(self):
        allowed, ask, off = tools.policy({"claude": {"allowed_tools": ["Read"], "disallowed_tools": ["X"]}})
        self.assertEqual((allowed, ask, off), (["Read"], [], ["X"]))
        allowed, ask, off = tools.policy({"tools": {"allowed": ["Read"], "ask": ["A", "B"]}}, granted=["A"])
        self.assertEqual((allowed, ask), (["Read", "A"], ["B"]))


if __name__ == "__main__":
    unittest.main()
