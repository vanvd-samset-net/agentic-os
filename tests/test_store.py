"""Phase 1: CSDL, máy trạng thái, checkout nguyên tử, khoá, thu hồi, duyệt, kiểm toán."""
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from aos import db, states, store


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "aos.db"
        self.con = db.connect(self.path)
        store.ensure_org(self.con, "Công ty thử", "Làm website an toàn")
        store.upsert_agent(self.con, "b3b4", "WP agent", "shell", role="B3+B4")
        store.upsert_agent(self.con, "b5", "Test agent", "shell", role="B5")
        g = store.add_goal(self.con, "Giao 2 site/tháng")
        store.add_project(self.con, "lop3d", "LỚP", goal_id=g)
        store.add_project(self.con, "manga", "MANGA")

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()


class StateMachineTest(Base):
    def test_add_with_agent_is_assigned_without_is_backlog(self):
        a = store.add_task(self.con, "lop3d", "Làm site", agent_id="b3b4")
        b = store.add_task(self.con, "lop3d", "Chưa giao")
        self.assertEqual(store.get_task(self.con, a)["status"], "assigned")
        self.assertEqual(store.get_task(self.con, b)["status"], "backlog")

    def test_human_cannot_mark_running_and_worker_cannot_approve(self):
        t = store.add_task(self.con, "lop3d", "x", agent_id="b3b4")
        with self.assertRaises(states.TransitionError):
            with db.Tx(self.con):
                store._set_status(self.con, store.get_task(self.con, t), "running", "human:van")
        task = store.checkout(self.con, "b3b4", "w1")
        store.finish(self.con, task["id"], task["run_id"], "w1", "succeeded", summary="xong")
        with self.assertRaises(states.TransitionError):
            store.review(self.con, t, True, actor="worker:w1")
        store.review(self.con, t, True, actor="human:van")
        self.assertEqual(store.get_task(self.con, t)["status"], "done")

    def test_done_is_terminal(self):
        t = store.add_task(self.con, "lop3d", "x", agent_id="b3b4")
        task = store.checkout(self.con, "b3b4", "w1")
        store.finish(self.con, t, task["run_id"], "w1", "succeeded")
        store.review(self.con, t, True)
        with self.assertRaises(states.TransitionError):
            store.cancel(self.con, t)

    def test_reject_requires_note_and_feeds_context(self):
        t = store.add_task(self.con, "lop3d", "x", agent_id="b3b4")
        task = store.checkout(self.con, "b3b4", "w1")
        store.finish(self.con, t, task["run_id"], "w1", "succeeded", summary="đã làm")
        with self.assertRaises(ValueError):
            store.review(self.con, t, False, note="")
        store.review(self.con, t, False, note="Thiếu trang liên hệ")
        self.assertEqual(store.get_task(self.con, t)["status"], "assigned")
        ctx = store.context_chain(self.con, t)
        self.assertIn("Thiếu trang liên hệ", [c["body"] for c in ctx["comments"] if c["kind"] == "feedback"])
        self.assertEqual(ctx["goals"][0]["title"], "Giao 2 site/tháng")
        self.assertEqual(ctx["org"]["mission"], "Làm website an toàn")


class CheckoutTest(Base):
    def test_only_one_worker_gets_the_task(self):
        t = store.add_task(self.con, "lop3d", "x", agent_id="b3b4")
        got, barrier = [], threading.Barrier(8)

        def worker(i):
            con = db.connect(self.path)
            barrier.wait()
            res = store.checkout(con, "b3b4", f"w{i}")
            if res:
                got.append(res["id"])
            con.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        [th.start() for th in threads]
        [th.join() for th in threads]
        self.assertEqual(got, [t])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)

    def test_dependencies_must_be_done(self):
        a = store.add_task(self.con, "lop3d", "thiết kế", agent_id="b3b4")
        b = store.add_task(self.con, "manga", "test", agent_id="b5", depends_on=[a])
        self.assertIsNone(store.checkout(self.con, "b5", "w1"))
        task = store.checkout(self.con, "b3b4", "w2")
        store.finish(self.con, a, task["run_id"], "w2", "succeeded")
        self.assertIsNone(store.checkout(self.con, "b5", "w1"))  # chờ duyệt chưa phải done
        store.review(self.con, a, True)
        self.assertEqual(store.checkout(self.con, "b5", "w1")["id"], b)

    def test_one_running_task_per_project(self):
        a = store.add_task(self.con, "lop3d", "a", agent_id="b3b4", priority=0)
        b = store.add_task(self.con, "lop3d", "b", agent_id="b3b4")
        c = store.add_task(self.con, "manga", "c", agent_id="b3b4")
        self.assertEqual(store.checkout(self.con, "b3b4", "w1")["id"], a)
        self.assertEqual(store.checkout(self.con, "b3b4", "w2")["id"], c)  # b bị giữ vì lop3d đang chạy
        self.assertIsNone(store.checkout(self.con, "b3b4", "w3"))
        self.assertEqual(store.checkout(self.con, "b3b4", "w3", exclusive_project=False)["id"], b)

    def test_paused_agent_gets_nothing(self):
        store.add_task(self.con, "lop3d", "x", agent_id="b3b4")
        store.upsert_agent(self.con, "b3b4", "WP agent", "shell", status="paused")
        self.assertIsNone(store.checkout(self.con, "b3b4", "w1"))


class LeaseTest(Base):
    def test_recover_expired_lease_retries_then_fails(self):
        t = store.add_task(self.con, "lop3d", "x", agent_id="b3b4", max_attempts=2)
        for expected in ("assigned", "failed"):
            task = store.checkout(self.con, "b3b4", "w1", lease=-1)  # khoá hết hạn ngay
            self.assertIsNotNone(task)
            self.assertEqual(store.recover(self.con), [(t, expected)])
        runs = [r["status"] for r in self.con.execute("SELECT status FROM runs ORDER BY id")]
        self.assertEqual(runs, ["lost", "lost"])

    def test_heartbeat_fails_after_cancel_and_finish_does_not_overwrite(self):
        t = store.add_task(self.con, "lop3d", "x", agent_id="b3b4")
        task = store.checkout(self.con, "b3b4", "w1")
        self.assertTrue(store.heartbeat(self.con, t, "w1"))
        self.assertFalse(store.heartbeat(self.con, t, "w2"))
        store.cancel(self.con, t)
        self.assertFalse(store.heartbeat(self.con, t, "w1"))
        self.assertEqual(store.finish(self.con, t, task["run_id"], "w1", "succeeded"), "cancelled")

    def test_failure_retries_until_max_attempts(self):
        t = store.add_task(self.con, "lop3d", "x", agent_id="b3b4", max_attempts=2)
        task = store.checkout(self.con, "b3b4", "w1")
        self.assertEqual(store.finish(self.con, t, task["run_id"], "w1", "failed", error="lỗi 1"), "assigned")
        task = store.checkout(self.con, "b3b4", "w1")
        self.assertEqual(store.finish(self.con, t, task["run_id"], "w1", "failed", error="lỗi 2"), "failed")
        store.reopen(self.con, t, note="đã sửa cấu hình")
        self.assertEqual(store.get_task(self.con, t)["attempts"], 0)

    def test_blocked_keeps_reason(self):
        t = store.add_task(self.con, "lop3d", "x", agent_id="b3b4")
        task = store.checkout(self.con, "b3b4", "w1")
        store.finish(self.con, t, task["run_id"], "w1", "blocked", blocked_reason="Cần tạo site trong Local")
        row = store.get_task(self.con, t)
        self.assertEqual((row["status"], row["blocked_reason"]), ("blocked", "Cần tạo site trong Local"))


class AuditTest(Base):
    def test_every_transition_is_audited_and_log_is_append_only(self):
        t = store.add_task(self.con, "lop3d", "x", agent_id="b3b4", actor="human:van")
        actions = [r["action"] for r in self.con.execute("SELECT action FROM audit_log WHERE entity = 'task' AND entity_id = ?", (str(t),))]
        self.assertEqual(actions, ["task.add", "task.status"])
        with self.assertRaises(sqlite3.DatabaseError):
            self.con.execute("UPDATE audit_log SET actor = 'x'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.con.execute("DELETE FROM audit_log")

    def test_usage_summary(self):
        t = store.add_task(self.con, "lop3d", "x", agent_id="b3b4")
        task = store.checkout(self.con, "b3b4", "w1")
        store.finish(self.con, t, task["run_id"], "w1", "succeeded",
                     usage={"input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 100, "cost_usd": 0.25})
        row = store.usage_summary(self.con)[0]
        self.assertEqual((row["agent_id"], row["output_tokens"], row["cost_usd"]), ("b3b4", 5, 0.25))


if __name__ == "__main__":
    unittest.main()
