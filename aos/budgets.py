"""Ngân sách token/USD theo công ty, dự án, agent, task (docs/07-ngan-sach-phe-duyet.md).

Chi tiêu tính từ bảng runs. Token = vào + ra + ghi cache + đọc cache. USD là ước tính của Claude Code.
"""
from datetime import datetime, timezone

from .db import Tx, now
from .store import audit

SCOPES = ("org", "project", "agent", "task")
TOKENS_SQL = "COALESCE(SUM(r.input_tokens + r.output_tokens + r.cache_read_tokens + r.cache_write_tokens), 0)"


def month_start():
    d = datetime.now(timezone.utc)
    return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


def set_budget(con, scope, scope_id="", usd=None, tokens=None, period="total", warn=0.8, actor="human:cli"):
    if scope not in SCOPES:
        raise ValueError(f"scope phải là {', '.join(SCOPES)}")
    if scope != "org" and not scope_id:
        raise ValueError("Cần --id cho phạm vi project/agent/task")
    if usd is None and tokens is None:
        raise ValueError("Cần ít nhất --usd hoặc --tokens")
    scope_id = "" if scope == "org" else str(scope_id)
    with Tx(con):
        con.execute(
            """INSERT INTO budgets (scope, scope_id, period, limit_usd, limit_tokens, warn_ratio, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(scope, scope_id, period) DO UPDATE SET limit_usd = excluded.limit_usd,
                 limit_tokens = excluded.limit_tokens, warn_ratio = excluded.warn_ratio, warned_key = NULL,
                 updated_at = excluded.updated_at""",
            (scope, scope_id, period, usd, tokens, warn, now(), now()))
        audit(con, actor, "budget.set", "budget", f"{scope}:{scope_id}:{period}", {"usd": usd, "tokens": tokens, "warn": warn})


def spent(con, budget):
    """(usd, tokens) đã dùng trong phạm vi + kỳ của một dòng budgets."""
    where, args = ["1 = 1"], []
    if budget["period"] == "month":
        where.append("r.started_at >= ?")
        args.append(month_start())
    scope, sid = budget["scope"], budget["scope_id"]
    if scope == "project":
        where.append("p.slug = ?")
        args.append(sid)
    elif scope == "agent":
        where.append("r.agent_id = ?")
        args.append(sid)
    elif scope == "task":
        where.append("r.task_id = ?")
        args.append(int(sid))
    row = con.execute(
        f"""SELECT COALESCE(SUM(r.cost_usd), 0) AS usd, {TOKENS_SQL} AS tokens FROM runs r
            JOIN tasks t ON t.id = r.task_id JOIN projects p ON p.id = t.project_id WHERE {' AND '.join(where)}""",
        args).fetchone()
    return float(row["usd"]), int(row["tokens"])


def applicable(con, task):
    """Các dòng ngân sách áp cho task (công ty + dự án của task + agent của task + chính task)."""
    slug = con.execute("SELECT slug FROM projects WHERE id = ?", (task["project_id"],)).fetchone()["slug"]
    rows = con.execute(
        """SELECT * FROM budgets WHERE scope = 'org' OR (scope = 'project' AND scope_id = ?)
           OR (scope = 'agent' AND scope_id = ?) OR (scope = 'task' AND scope_id = ?)""",
        (slug, task["agent_id"] or "", str(task["id"]))).fetchall()
    return [dict(r) for r in rows]


def status(con, budget):
    usd, tokens = spent(con, budget)
    ratios = []
    if budget["limit_usd"] is not None:
        ratios.append(usd / budget["limit_usd"] if budget["limit_usd"] > 0 else float("inf"))
    if budget["limit_tokens"] is not None:
        ratios.append(tokens / budget["limit_tokens"] if budget["limit_tokens"] > 0 else float("inf"))
    ratio = max(ratios) if ratios else 0.0
    remaining_usd = None if budget["limit_usd"] is None else max(0.0, budget["limit_usd"] - usd)
    return {**budget, "spent_usd": round(usd, 6), "spent_tokens": tokens, "ratio": ratio, "remaining_usd": remaining_usd}


def label(b):
    return f"{b['scope']}{':' + b['scope_id'] if b['scope_id'] else ''} ({b['period']})"


def check(con, task):
    """Trước khi chạy: trả (danh sách ngân sách đã hết, USD còn lại nhỏ nhất hoặc None)."""
    exceeded, remaining = [], []
    for b in applicable(con, task):
        s = status(con, b)
        if s["ratio"] >= 1:
            exceeded.append(s)
        if s["remaining_usd"] is not None:
            remaining.append(s["remaining_usd"])
    return exceeded, (min(remaining) if remaining else None)


def after_run(con, task, actor):
    """Sau khi chạy: cảnh báo khi vượt ngưỡng (một lần mỗi kỳ); hết ngân sách agent → tự tạm dừng agent."""
    events = []
    for b in applicable(con, task):
        s = status(con, b)
        key = month_start()[:7] if b["period"] == "month" else "total"
        if s["ratio"] >= b["warn_ratio"] and b["warned_key"] != key:
            with Tx(con):
                con.execute("UPDATE budgets SET warned_key = ? WHERE id = ?", (key, b["id"]))
                audit(con, actor, "budget.warn", "budget", label(b), {"ratio": round(s["ratio"], 3),
                                                                      "spent_usd": s["spent_usd"], "spent_tokens": s["spent_tokens"]})
                con.execute("INSERT INTO task_comments (task_id, author, kind, body, created_at) VALUES (?, ?, 'note', ?, ?)",
                            (task["id"], "system", f"Cảnh báo ngân sách {label(b)}: đã dùng {s['ratio']:.0%} "
                             f"(${s['spent_usd']:.2f}, {s['spent_tokens']:,} token).", now()))
            events.append(("warn", label(b)))
        if b["scope"] == "agent" and s["ratio"] >= 1:
            with Tx(con):
                cur = con.execute("UPDATE agents SET status = 'paused', updated_at = ? WHERE id = ? AND status = 'active'",
                                  (now(), b["scope_id"]))
                if cur.rowcount:
                    audit(con, actor, "agent.auto_pause", "agent", b["scope_id"], {"reason": f"hết ngân sách {label(b)}"})
            events.append(("pause", b["scope_id"]))
    return events


def raise_limit(con, budget_id, usd=None, tokens=None, actor="human:cli"):
    with Tx(con):
        b = con.execute("SELECT * FROM budgets WHERE id = ?", (budget_id,)).fetchone()
        if not b:
            raise LookupError(f"Không có ngân sách #{budget_id}")
        new_usd = (b["limit_usd"] or 0) + usd if usd else b["limit_usd"]
        new_tok = (b["limit_tokens"] or 0) + tokens if tokens else b["limit_tokens"]
        con.execute("UPDATE budgets SET limit_usd = ?, limit_tokens = ?, warned_key = NULL, updated_at = ? WHERE id = ?",
                    (new_usd, new_tok, now(), budget_id))
        audit(con, actor, "budget.raise", "budget", label(dict(b)), {"usd": new_usd, "tokens": new_tok})


def list_all(con):
    return [status(con, dict(r)) for r in con.execute("SELECT * FROM budgets ORDER BY scope, scope_id, period")]
