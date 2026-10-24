"""Control plane: mọi thay đổi dữ liệu đi qua đây, cùng giao dịch với audit_log (docs/02, docs/03)."""
import json

from . import states
from .db import Tx, now

LEASE_SECONDS = 120  # khoá task; worker gia hạn trong lúc chạy


class NotFound(LookupError):
    pass


def audit(con, actor, action, entity, entity_id=None, data=None):
    """Ghi kiểm toán. Không bao giờ truyền bí mật vào data."""
    con.execute(
        "INSERT INTO audit_log (ts, actor, action, entity, entity_id, data_json) VALUES (?, ?, ?, ?, ?, ?)",
        (now(), actor, action, entity, None if entity_id is None else str(entity_id),
         json.dumps(data or {}, ensure_ascii=False)),
    )


# ------------------------------------------------------------------ tổ chức, agent, mục tiêu, dự án

def ensure_org(con, name, mission="", actor="system"):
    row = con.execute("SELECT * FROM organizations ORDER BY id LIMIT 1").fetchone()
    with Tx(con):
        if row:
            con.execute("UPDATE organizations SET name = ?, mission = ? WHERE id = ?", (name, mission, row["id"]))
            org_id = row["id"]
        else:
            org_id = con.execute("INSERT INTO organizations (name, mission, created_at) VALUES (?, ?, ?)",
                                 (name, mission, now())).lastrowid
        audit(con, actor, "org.upsert", "organization", org_id, {"name": name})
    return org_id


def org_id(con):
    row = con.execute("SELECT id FROM organizations ORDER BY id LIMIT 1").fetchone()
    if not row:
        raise NotFound("Chưa có tổ chức: chạy `aos init`.")
    return row["id"]


def upsert_agent(con, agent_id, name, adapter, role="", reports_to=None, config=None, status="active", actor="system"):
    """status=None: agent mới là active, agent cũ giữ nguyên trạng thái (vd đã tự tạm dừng vì hết ngân sách)."""
    oid = org_id(con)
    with Tx(con):
        con.execute(
            """INSERT INTO agents (id, org_id, name, role, reports_to, adapter, config_json, status, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET name = excluded.name, role = excluded.role, reports_to = excluded.reports_to,
                 adapter = excluded.adapter, config_json = excluded.config_json,
                 status = CASE WHEN ? IS NULL THEN agents.status ELSE excluded.status END, updated_at = excluded.updated_at""",
            (agent_id, oid, name, role, reports_to, adapter, json.dumps(config or {}, ensure_ascii=False), status or "active",
             now(), status),
        )
        audit(con, actor, "agent.upsert", "agent", agent_id, {"adapter": adapter, "status": status})


def get_agent(con, agent_id):
    row = con.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    if not row:
        raise NotFound(f"Không có agent {agent_id}")
    agent = dict(row)
    agent["config"] = json.loads(agent.pop("config_json") or "{}")
    return agent


def add_goal(con, title, description="", parent_id=None, actor="system"):
    with Tx(con):
        gid = con.execute("INSERT INTO goals (org_id, parent_id, title, description, created_at) VALUES (?, ?, ?, ?, ?)",
                          (org_id(con), parent_id, title, description, now())).lastrowid
        audit(con, actor, "goal.add", "goal", gid, {"title": title})
    return gid


def add_project(con, slug, name, description="", goal_id=None, actor="system"):
    with Tx(con):
        pid = con.execute(
            "INSERT INTO projects (org_id, goal_id, slug, name, description, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (org_id(con), goal_id, slug, name, description, now())).lastrowid
        audit(con, actor, "project.add", "project", pid, {"slug": slug})
    return pid


def project_by_slug(con, slug):
    row = con.execute("SELECT * FROM projects WHERE slug = ?", (slug,)).fetchone()
    if not row:
        raise NotFound(f"Không có dự án {slug}")
    return dict(row)


# ------------------------------------------------------------------ task

def get_task(con, task_id):
    row = con.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise NotFound(f"Không có task {task_id}")
    return dict(row)


def _set_status(con, task, target, actor, **fields):
    """Chuyển trạng thái có kiểm luật; gọi bên trong Tx."""
    states.check(task["status"], target, actor)
    sets = {"status": target, "updated_at": now(), **fields}
    con.execute(f"UPDATE tasks SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ? AND status = ?",
                (*sets.values(), task["id"], task["status"]))
    audit(con, actor, "task.status", "task", task["id"], {"from": task["status"], "to": target,
                                                         **{k: v for k, v in fields.items() if k != "lock_until"}})


def add_task(con, project_slug, title, description="", agent_id=None, priority=2, parent_id=None, depends_on=(),
             max_attempts=2, actor="human:cli"):
    project = project_by_slug(con, project_slug)
    if agent_id:
        agent = get_agent(con, agent_id)
        if agent["status"] != "active":
            raise states.TransitionError(f"Agent {agent_id} đang tạm dừng")
    with Tx(con):
        tid = con.execute(
            """INSERT INTO tasks (project_id, parent_id, title, description, agent_id, status, priority, max_attempts,
               created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'backlog', ?, ?, ?, ?, ?)""",
            (project["id"], parent_id, title, description, agent_id, priority, max_attempts, actor, now(), now())).lastrowid
        for dep in depends_on:
            con.execute("INSERT INTO task_deps (task_id, depends_on) VALUES (?, ?)", (tid, int(dep)))
        audit(con, actor, "task.add", "task", tid, {"title": title, "agent": agent_id, "depends_on": list(depends_on)})
        if agent_id:
            _set_status(con, get_task(con, tid), "assigned", actor)
    return tid


def assign(con, task_id, agent_id, actor="human:cli"):
    agent = get_agent(con, agent_id)
    if agent["status"] != "active":
        raise states.TransitionError(f"Agent {agent_id} đang tạm dừng")
    with Tx(con):
        task = get_task(con, task_id)
        if task["status"] == "assigned":  # đổi người nhận
            con.execute("UPDATE tasks SET agent_id = ?, updated_at = ? WHERE id = ?", (agent_id, now(), task_id))
            audit(con, actor, "task.reassign", "task", task_id, {"agent": agent_id})
        else:
            con.execute("UPDATE tasks SET agent_id = ? WHERE id = ?", (agent_id, task_id))
            _set_status(con, task, "assigned", actor)


def comment(con, task_id, author, body, kind="note"):
    get_task(con, task_id)
    with Tx(con):
        cid = con.execute("INSERT INTO task_comments (task_id, author, kind, body, created_at) VALUES (?, ?, ?, ?, ?)",
                          (task_id, author, kind, body, now())).lastrowid
        audit(con, author, "task.comment", "task", task_id, {"kind": kind})
    return cid


def review(con, task_id, approve, note="", actor="human:cli"):
    with Tx(con):
        task = get_task(con, task_id)
        if approve:
            _set_status(con, task, "done", actor)
        else:
            if not note.strip():
                raise ValueError("Trả lại task cần ghi lý do (góp ý cho agent).")
            _set_status(con, task, "assigned", actor, attempts=0)
        if note.strip():
            con.execute("INSERT INTO task_comments (task_id, author, kind, body, created_at) VALUES (?, ?, ?, ?, ?)",
                        (task_id, actor, "note" if approve else "feedback", note, now()))


def reopen(con, task_id, actor="human:cli", note=""):
    """blocked/failed → assigned (người đã xử lý việc chặn hoặc cho thử lại)."""
    with Tx(con):
        _set_status(con, get_task(con, task_id), "assigned", actor, attempts=0, blocked_reason=None)
        if note.strip():
            con.execute("INSERT INTO task_comments (task_id, author, kind, body, created_at) VALUES (?, ?, ?, ?, ?)",
                        (task_id, actor, "feedback", note, now()))


def cancel(con, task_id, actor="human:cli"):
    with Tx(con):
        _set_status(con, get_task(con, task_id), "cancelled", actor, lock_owner=None, lock_until=None)


# ------------------------------------------------------------------ checkout, khoá, thu hồi

def checkout(con, agent_id, worker_id, exclusive_project=True, lease=LEASE_SECONDS):
    """Lấy task kế tiếp cho agent một cách nguyên tử. Trả task (đã running, đã có run) hoặc None.

    Điều kiện: đúng agent, agent active, trạng thái assigned, mọi phụ thuộc done; nếu exclusive_project thì
    dự án không có task nào khác đang running (agent dùng chung thư mục làm việc theo dự án).
    """
    actor = f"worker:{worker_id}"
    with Tx(con):
        row = con.execute(
            f"""SELECT t.* FROM tasks t JOIN agents a ON a.id = t.agent_id
                WHERE t.agent_id = ? AND a.status = 'active' AND t.status = 'assigned'
                  AND NOT EXISTS (SELECT 1 FROM task_deps d JOIN tasks p ON p.id = d.depends_on
                                  WHERE d.task_id = t.id AND p.status <> 'done')
                  {"AND NOT EXISTS (SELECT 1 FROM tasks o WHERE o.project_id = t.project_id AND o.status = 'running')"
                   if exclusive_project else ""}
                ORDER BY t.priority, t.id LIMIT 1""",
            (agent_id,)).fetchone()
        if not row:
            return None
        task = dict(row)
        _set_status(con, task, "running", actor, lock_owner=worker_id, lock_until=now(lease),
                    attempts=task["attempts"] + 1)
        run_id = con.execute("INSERT INTO runs (task_id, agent_id, worker_id, status, started_at) VALUES (?, ?, ?, 'running', ?)",
                             (task["id"], agent_id, worker_id, now())).lastrowid
        audit(con, actor, "run.start", "run", run_id, {"task": task["id"]})
    task = get_task(con, task["id"])
    task["run_id"] = run_id
    return task


def heartbeat(con, task_id, worker_id, lease=LEASE_SECONDS):
    """Gia hạn khoá. False nếu khoá đã mất (bị thu hồi / huỷ) → worker phải dừng agent."""
    with Tx(con):
        cur = con.execute("UPDATE tasks SET lock_until = ? WHERE id = ? AND status = 'running' AND lock_owner = ?",
                          (now(lease), task_id, worker_id))
    return cur.rowcount == 1


def finish(con, task_id, run_id, worker_id, outcome, summary="", usage=None, exit_code=None, session_id=None,
           log_dir=None, error=None, blocked_reason=None, approval=None, refund_attempt=False):
    """Kết thúc lần chạy. outcome: succeeded | blocked | failed | timeout | cancelled.
    approval=(kind, request) → task chuyển needs_approval và tạo yêu cầu phê duyệt (Phase 3);
    refund_attempt: không tính lượt thử (lần chạy bị chặn trước khi agent chạy)."""
    actor = f"worker:{worker_id}"
    u = usage or {}
    with Tx(con):
        con.execute(
            """UPDATE runs SET status = ?, ended_at = ?, exit_code = ?, session_id = ?, input_tokens = ?, output_tokens = ?,
               cache_read_tokens = ?, cache_write_tokens = ?, cost_usd = ?, num_turns = ?, log_dir = ?, error = ?
               WHERE id = ?""",
            (outcome, now(), exit_code, session_id, int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0)),
             int(u.get("cache_read_tokens", 0)), int(u.get("cache_write_tokens", 0)), float(u.get("cost_usd", 0) or 0),
             u.get("num_turns"), log_dir, (error or "")[:2000] or None, run_id))
        task = get_task(con, task_id)
        if task["status"] != "running" or task["lock_owner"] != worker_id:
            audit(con, actor, "run.orphan", "run", run_id, {"task_status": task["status"]})
            return task["status"]  # đã bị huỷ/thu hồi trong lúc chạy: không ghi đè
        common = {"lock_owner": None, "lock_until": None}
        if refund_attempt:
            common["attempts"] = max(0, task["attempts"] - 1)
        if approval:
            kind, request = approval
            target = "needs_approval"
            _set_status(con, task, target, actor, result_summary=(summary or error or "")[:4000], **common)
            aid = con.execute("INSERT INTO approvals (task_id, run_id, kind, request_json, requested_at) VALUES (?, ?, ?, ?, ?)",
                              (task_id, run_id, kind, json.dumps({**request, "run_outcome": outcome}, ensure_ascii=False),
                               now())).lastrowid
            audit(con, actor, "approval.request", "approval", aid, {"task": task_id, "kind": kind})
        elif outcome == "succeeded":
            target = "under_review"
            _set_status(con, task, target, actor, result_summary=summary[:4000], **common)
        elif outcome == "blocked":
            target = "blocked"
            _set_status(con, task, target, actor, blocked_reason=(blocked_reason or summary)[:2000], **common)
        else:
            target = "assigned" if task["attempts"] < task["max_attempts"] and outcome != "cancelled" else "failed"
            _set_status(con, task, target, actor, result_summary=(error or summary)[:4000], **common)
        if summary:
            con.execute("INSERT INTO task_comments (task_id, author, kind, body, created_at) VALUES (?, ?, 'agent', ?, ?)",
                        (task_id, f"agent:{task['agent_id']}", summary[:4000], now()))
        audit(con, actor, "run.finish", "run", run_id, {"outcome": outcome, "task_to": target,
                                                        "cost_usd": u.get("cost_usd", 0)})
    return target


def recover(con, actor="system"):
    """Thu hồi task có khoá hết hạn (worker chết): run → lost; task → assigned (còn lượt) hoặc failed."""
    out = []
    with Tx(con):
        for row in con.execute("SELECT * FROM tasks WHERE status = 'running' AND lock_until < ?", (now(),)).fetchall():
            task = dict(row)
            con.execute("UPDATE runs SET status = 'lost', ended_at = ?, error = 'khoá hết hạn: worker không còn gia hạn' "
                        "WHERE task_id = ? AND status = 'running'", (now(), task["id"]))
            target = "assigned" if task["attempts"] < task["max_attempts"] else "failed"
            _set_status(con, task, target, actor, lock_owner=None, lock_until=None)
            out.append((task["id"], target))
    return out


# ------------------------------------------------------------------ phê duyệt (Phase 3)

def get_approval(con, approval_id):
    row = con.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
    if not row:
        raise NotFound(f"Không có yêu cầu phê duyệt #{approval_id}")
    a = dict(row)
    a["request"] = json.loads(a.pop("request_json") or "{}")
    return a


def list_approvals(con, pending_only=True):
    sql = "SELECT a.*, t.title FROM approvals a JOIN tasks t ON t.id = a.task_id"
    rows = con.execute(sql + (" WHERE a.status = 'pending'" if pending_only else "") + " ORDER BY a.id").fetchall()
    out = []
    for r in rows:
        a = dict(r)
        a["request"] = json.loads(a.pop("request_json") or "{}")
        out.append(a)
    return out


def grants(con, task_id):
    return [r["rule"] for r in con.execute("SELECT rule FROM task_grants WHERE task_id = ? ORDER BY rule", (task_id,))]


def decide(con, approval_id, approve, note="", actor="human:cli", raise_usd=None, raise_tokens=None):
    """Duyệt / từ chối. Duyệt budget: tăng hạn mức (nếu có) rồi phải hết bị vượt; duyệt tool: cấp luật cho riêng task."""
    from . import budgets  # tránh vòng import
    a = get_approval(con, approval_id)
    if a["status"] != "pending":
        raise ValueError(f"Yêu cầu #{approval_id} đã {a['status']}")
    task = get_task(con, a["task_id"])
    if approve and a["kind"] == "budget":
        for bid in a["request"].get("budget_ids", []):
            if raise_usd or raise_tokens:
                budgets.raise_limit(con, bid, raise_usd, raise_tokens, actor=actor)
        still, _ = budgets.check(con, task)
        if still:
            raise ValueError("Vẫn hết ngân sách: " + ", ".join(budgets.label(b) for b in still)
                             + ". Duyệt kèm --raise-usd / --raise-tokens hoặc `aos budget set`.")
    with Tx(con):
        task = get_task(con, a["task_id"])
        con.execute("UPDATE approvals SET status = ?, decided_at = ?, decided_by = ?, decision_note = ? WHERE id = ?",
                    ("approved" if approve else "denied", now(), actor, note, approval_id))
        audit(con, actor, "approval.approve" if approve else "approval.deny", "approval", approval_id,
              {"task": task["id"], "kind": a["kind"]})
        if approve:
            for rule in a["request"].get("rules", []) if a["kind"] == "tool" else []:
                con.execute("INSERT OR IGNORE INTO task_grants (task_id, rule, approval_id, granted_by, granted_at) "
                            "VALUES (?, ?, ?, ?, ?)", (task["id"], rule, approval_id, actor, now()))
            target = "assigned"
        else:
            target = "under_review" if a["request"].get("run_outcome") == "succeeded" and a["kind"] == "tool" else "failed"
        if task["status"] == "needs_approval":
            _set_status(con, task, target, actor)
        if note.strip():
            con.execute("INSERT INTO task_comments (task_id, author, kind, body, created_at) VALUES (?, ?, ?, ?, ?)",
                        (task["id"], actor, "feedback" if approve else "note", note, now()))
    return target


def resume_agent(con, agent_id, actor="human:cli"):
    get_agent(con, agent_id)
    with Tx(con):
        con.execute("UPDATE agents SET status = 'active', updated_at = ? WHERE id = ?", (now(), agent_id))
        audit(con, actor, "agent.resume", "agent", agent_id)


# ------------------------------------------------------------------ đọc

def context_chain(con, task_id):
    """Ngữ cảnh "vì sao": sứ mệnh → mục tiêu (cha → con) → dự án → task cha → task → góp ý/nhật ký trước."""
    task = get_task(con, task_id)
    project = dict(con.execute("SELECT * FROM projects WHERE id = ?", (task["project_id"],)).fetchone())
    org = dict(con.execute("SELECT * FROM organizations WHERE id = ?", (project["org_id"],)).fetchone())
    goals, gid = [], project["goal_id"]
    while gid:
        g = dict(con.execute("SELECT * FROM goals WHERE id = ?", (gid,)).fetchone())
        goals.insert(0, g)
        gid = g["parent_id"]
    parent = get_task(con, task["parent_id"]) if task["parent_id"] else None
    comments = [dict(r) for r in con.execute(
        "SELECT * FROM task_comments WHERE task_id = ? ORDER BY id", (task_id,)).fetchall()]
    return {"org": org, "goals": goals, "project": project, "parent": parent, "task": task, "comments": comments}


def list_tasks(con, status=None, agent_id=None):
    sql, args = "SELECT t.*, p.slug AS project FROM tasks t JOIN projects p ON p.id = t.project_id WHERE 1 = 1", []
    if status:
        sql += " AND t.status = ?"
        args.append(status)
    if agent_id:
        sql += " AND t.agent_id = ?"
        args.append(agent_id)
    return [dict(r) for r in con.execute(sql + " ORDER BY t.status, t.priority, t.id", args).fetchall()]


def usage_summary(con):
    return [dict(r) for r in con.execute(
        """SELECT agent_id, COUNT(*) AS runs, SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
                  SUM(cache_read_tokens) AS cache_read_tokens, SUM(cache_write_tokens) AS cache_write_tokens,
                  ROUND(SUM(cost_usd), 4) AS cost_usd
           FROM runs GROUP BY agent_id ORDER BY agent_id""").fetchall()]
