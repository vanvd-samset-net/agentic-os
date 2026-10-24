"""CLI: python -m aos <lệnh>. Xem README.md."""
import argparse
import getpass
import json
import sys

from . import config, db, store, worker

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")


def human():
    return f"human:{getpass.getuser()}"


def table(rows, cols):
    if not rows:
        print("(trống)")
        return
    widths = {c: max(len(c), *(len(str(r.get(c, "") if r.get(c) is not None else "")) for r in rows)) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c) if r.get(c) is not None else "").ljust(widths[c]) for c in cols))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="aos", description="agentic-os: điều phối agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="tạo CSDL, nạp tổ chức + agent từ config/agents.toml")
    sub.add_parser("agents", help="danh sách agent")
    g = sub.add_parser("goal", help="thêm mục tiêu")
    g.add_argument("title"), g.add_argument("--desc", default=""), g.add_argument("--parent", type=int)
    p = sub.add_parser("project", help="thêm dự án")
    p.add_argument("slug"), p.add_argument("name"), p.add_argument("--desc", default=""), p.add_argument("--goal", type=int)
    t = sub.add_parser("add", help="thêm task")
    t.add_argument("project"), t.add_argument("title"), t.add_argument("--desc", default="")
    t.add_argument("--agent"), t.add_argument("--priority", type=int, default=2), t.add_argument("--parent", type=int)
    t.add_argument("--after", type=int, nargs="*", default=[], help="chỉ chạy sau các task này done")
    t.add_argument("--attempts", type=int, default=2)
    ls = sub.add_parser("list", help="danh sách task")
    ls.add_argument("--status"), ls.add_argument("--agent")
    sh = sub.add_parser("show", help="chi tiết task: lần chạy, trao đổi, kiểm toán")
    sh.add_argument("id", type=int)
    a = sub.add_parser("assign", help="giao task")
    a.add_argument("id", type=int), a.add_argument("agent")
    c = sub.add_parser("comment", help="thêm ghi chú/góp ý")
    c.add_argument("id", type=int), c.add_argument("body"), c.add_argument("--feedback", action="store_true")
    r = sub.add_parser("review", help="duyệt task chờ duyệt")
    r.add_argument("id", type=int)
    grp = r.add_mutually_exclusive_group(required=True)
    grp.add_argument("--approve", action="store_true"), grp.add_argument("--reject", metavar="LÝ_DO")
    r.add_argument("--note", default="")
    ro = sub.add_parser("reopen", help="blocked/failed → giao lại")
    ro.add_argument("id", type=int), ro.add_argument("--note", default="")
    x = sub.add_parser("cancel", help="huỷ task")
    x.add_argument("id", type=int)
    w = sub.add_parser("worker", help="chạy worker cho một agent")
    w.add_argument("--agent", required=True), w.add_argument("--once", action="store_true")
    w.add_argument("--poll", type=int, default=30), w.add_argument("--id", default=None)
    sub.add_parser("recover", help="thu hồi task có khoá hết hạn")
    sub.add_parser("status", help="tổng quan: số task theo trạng thái, token/chi phí theo agent")
    args = ap.parse_args(argv)

    con = db.connect()
    try:
        if args.cmd == "init":
            cfg = config.load()
            print("Đã nạp agent:", ", ".join(config.sync(con, cfg, actor=human())))
        elif args.cmd == "agents":
            table([dict(r) for r in con.execute("SELECT id, name, role, reports_to, adapter, status FROM agents")],
                  ["id", "name", "role", "reports_to", "adapter", "status"])
        elif args.cmd == "goal":
            print("goal #", store.add_goal(con, args.title, args.desc, args.parent, actor=human()))
        elif args.cmd == "project":
            print("project #", store.add_project(con, args.slug, args.name, args.desc, args.goal, actor=human()))
        elif args.cmd == "add":
            tid = store.add_task(con, args.project, args.title, args.desc, args.agent, args.priority, args.parent,
                                 args.after, args.attempts, actor=human())
            print(f"task #{tid} → {store.get_task(con, tid)['status']}")
        elif args.cmd == "list":
            table(store.list_tasks(con, args.status, args.agent),
                  ["id", "project", "status", "agent_id", "priority", "attempts", "title"])
        elif args.cmd == "show":
            ctx = store.context_chain(con, args.id)
            task = ctx["task"]
            print(json.dumps({k: task[k] for k in ("id", "title", "status", "agent_id", "attempts", "max_attempts",
                                                   "blocked_reason", "result_summary")}, ensure_ascii=False, indent=1))
            print("\nLần chạy:")
            table([dict(r) for r in con.execute(
                "SELECT id, status, started_at, ended_at, output_tokens, cache_read_tokens, cost_usd, log_dir FROM runs "
                "WHERE task_id = ? ORDER BY id", (args.id,))],
                ["id", "status", "started_at", "ended_at", "output_tokens", "cache_read_tokens", "cost_usd", "log_dir"])
            print("\nTrao đổi:")
            for cm in ctx["comments"]:
                print(f"- [{cm['kind']}] {cm['author']} {cm['created_at']}: {cm['body'][:300]}")
            print("\nKiểm toán:")
            table([dict(r) for r in con.execute("SELECT ts, actor, action, data_json FROM audit_log WHERE entity = 'task' "
                                                "AND entity_id = ? ORDER BY id", (str(args.id),))],
                  ["ts", "actor", "action", "data_json"])
        elif args.cmd == "assign":
            store.assign(con, args.id, args.agent, actor=human())
        elif args.cmd == "comment":
            store.comment(con, args.id, human(), args.body, "feedback" if args.feedback else "note")
        elif args.cmd == "review":
            store.review(con, args.id, bool(args.approve), args.reject or args.note, actor=human())
            print(f"task #{args.id} → {store.get_task(con, args.id)['status']}")
        elif args.cmd == "reopen":
            store.reopen(con, args.id, actor=human(), note=args.note)
        elif args.cmd == "cancel":
            store.cancel(con, args.id, actor=human())
        elif args.cmd == "worker":
            worker.loop(con, args.agent, args.id or worker.default_worker_id(), config.CONFIG.parent.parent,
                        poll=args.poll, once=args.once)
        elif args.cmd == "recover":
            print(store.recover(con, actor=human()) or "Không có task nào hết hạn khoá.")
        elif args.cmd == "status":
            table([dict(r) for r in con.execute("SELECT status, COUNT(*) AS so_task FROM tasks GROUP BY status")],
                  ["status", "so_task"])
            print()
            table(store.usage_summary(con), ["agent_id", "runs", "input_tokens", "output_tokens", "cache_read_tokens",
                                             "cache_write_tokens", "cost_usd"])
    except (store.NotFound, ValueError, KeyError, config.ConfigError) as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
