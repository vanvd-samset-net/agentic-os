"""Worker (docs/04-worker-adapter.md): thu hồi khoá hết hạn → checkout → ngữ cảnh → adapter → kết quả → trạng thái."""
import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

from . import adapters, budgets, db, secrets, store, tools, workspace
from .adapters.base import AdapterResult, RunContext

DEFAULT_TEMPLATE = """# Việc được giao (agentic-os)

{context}

## Yêu cầu
- Làm task trên theo luật của chính bạn (AGENTS.md / CLAUDE.md trong thư mục làm việc).
- Góp ý của người duyệt (nếu có) là bắt buộc phải xử lý.
- Dòng cuối cùng: `AOS_RESULT: done|blocked|failed - <tóm tắt một câu>`.
"""


def default_worker_id():
    return f"{socket.gethostname()}-{os.getpid()}"


def render_context(ctx):
    """Chuỗi "vì sao": sứ mệnh → mục tiêu → dự án → task cha → task → trao đổi trước."""
    lines = []
    if ctx["org"].get("mission"):
        lines.append(f"**Sứ mệnh {ctx['org']['name']}:** {ctx['org']['mission']}")
    for g in ctx["goals"]:
        lines.append(f"**Mục tiêu:** {g['title']}" + (f" — {g['description']}" if g["description"] else ""))
    p = ctx["project"]
    lines.append(f"**Dự án:** {p['name']} (mã `{p['slug']}`)" + (f" — {p['description']}" if p["description"] else ""))
    if ctx["parent"]:
        lines.append(f"**Task cha #{ctx['parent']['id']}:** {ctx['parent']['title']}")
    t = ctx["task"]
    lines += ["", f"## Task #{t['id']}: {t['title']}", t["description"] or "(không có mô tả thêm)"]
    if ctx["comments"]:
        lines += ["", "## Trao đổi trước (cũ → mới)"]
        for c in ctx["comments"][-20:]:
            label = {"feedback": "GÓP Ý CẦN XỬ LÝ", "agent": "kết quả lần trước", "plan": "kế hoạch"}.get(c["kind"], "ghi chú")
            lines.append(f"- [{label}] {c['author']}: {c['body'][:1500]}")
    return "\n".join(lines)


def build_prompt(agent_cfg, ctx, base_dir):
    tpl = DEFAULT_TEMPLATE
    if agent_cfg.get("prompt_file"):
        tpl = (Path(base_dir) / agent_cfg["prompt_file"]).read_text(encoding="utf-8")
    values = {"context": render_context(ctx), "project_slug": ctx["project"]["slug"], "task_id": ctx["task"]["id"],
              "task_title": ctx["task"]["title"], "task_description": ctx["task"]["description"]}
    for k, v in values.items():
        tpl = tpl.replace("{" + k + "}", str(v))
    return tpl


def expand(value, task, project):
    return str(value).replace("{project_slug}", project["slug"]).replace("{task_id}", str(task["id"]))


def apply_handoff(agent_cfg, workdir, task, project, started, result: AdapterResult):
    """Hợp đồng đầu ra của agent (tuỳ chọn): [agents.<id>.handoff] file = "projects/{project_slug}/output/handoff.json",
    status_key = "status", done = ["done"], blocked = ["blocked"], failed = ["failed"], reason_key = "reason".
    Chỉ tin file được ghi sau lúc bắt đầu chạy (tránh đọc kết quả cũ)."""
    h = agent_cfg.get("handoff")
    if not h or result.outcome in ("timeout", "cancelled"):
        return result
    path = Path(workdir) / expand(h["file"], task, project)
    if not path.exists() or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < started:
        if result.outcome == "succeeded":
            result.outcome, result.error = "failed", f"Agent không ghi hợp đồng đầu ra mới ({path.name})"
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        result.outcome, result.error = "failed", f"Hợp đồng đầu ra hỏng: {e}"
        return result
    status = str(data.get(h.get("status_key", "status"), "")).lower()
    reason = str(data.get(h.get("reason_key", "reason"), "") or "")
    if status in h.get("done", ["done"]):
        result.outcome = "succeeded" if result.outcome in ("succeeded", "blocked") else result.outcome
    elif status in h.get("blocked", ["blocked"]):
        result.outcome, result.summary = "blocked", reason or result.summary
    elif status in h.get("failed", ["failed"]):
        result.outcome, result.error = "failed", reason or result.error or "agent báo failed"
    return result


def run_once(con, agent_id, worker_id, base_dir, heartbeat_every=30):
    """Một nhịp: trả (task_id, trạng thái mới) hoặc None khi không có việc."""
    store.recover(con, actor=f"worker:{worker_id}")
    agent = store.get_agent(con, agent_id)
    cfg = agent["config"]
    task = store.checkout(con, agent_id, worker_id, exclusive_project=cfg.get("workspace", "shared") == "shared")
    if not task:
        return None
    run_id, started = task["run_id"], datetime.now(timezone.utc)
    log_dir = db.DATA / "runs" / f"run-{run_id}"
    log_dir.mkdir(parents=True, exist_ok=True)
    ctx_data = store.context_chain(con, task["id"])
    project = ctx_data["project"]
    secret_values = {}
    actor = f"worker:{worker_id}"
    exceeded, remaining_usd = budgets.check(con, task)
    if exceeded:  # 1) trước khi chạy: hết ngân sách → không chạy agent, chờ duyệt, không tính lượt
        reason = "Hết ngân sách: " + "; ".join(budget_text(b) for b in exceeded)
        target = store.finish(con, task["id"], run_id, worker_id, "cancelled", error=reason, log_dir=str(log_dir),
                              approval=("budget", {"reason": reason, "budget_ids": [b["id"] for b in exceeded]}),
                              refund_attempt=True)
        return task["id"], target
    allowed, ask, off = tools.policy(cfg, store.grants(con, task["id"]))
    try:
        workdir = workspace.prepare(cfg, task)
        secret_values = secrets.load_for(agent_id, cfg.get("secrets") or [])
        env = secrets.build_env({k: expand(v, task, project) for k, v in (cfg.get("env") or {}).items()}, secret_values)
        prompt = build_prompt(cfg, ctx_data, base_dir)
        (log_dir / "prompt.md").write_text(prompt, encoding="utf-8")
        ctx = RunContext(task=task, project=project, agent=agent, prompt=prompt, workdir=Path(workdir), env=env,
                         log_dir=log_dir, timeout_s=int(cfg.get("timeout_s") or int(cfg.get("timeout_min", 60)) * 60),
                         heartbeat=lambda: store.heartbeat(con, task["id"], worker_id), heartbeat_every=heartbeat_every,
                         allowed_tools=allowed, off_tools=off, max_budget_usd=remaining_usd)
        result = adapters.REGISTRY[agent["adapter"]](ctx)
        result = apply_handoff(cfg, workdir, task, project, started, result)
    except Exception as e:  # noqa: BLE001 - lỗi chuẩn bị (thiếu bí mật, thư mục...) → lần chạy thất bại, không treo task
        result = AdapterResult(None, "failed", error=f"{type(e).__name__}: {e}")
    secrets.redact_files([log_dir / n for n in ("stdout.log", "stderr.log", "result.json", "prompt.md")], secret_values)
    if result.denials:
        (log_dir / "permission_denials.json").write_text(json.dumps(result.denials, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    summary = secrets.redact(result.summary or "", secret_values)
    if result.denials:
        summary = (summary + f"\n[{len(result.denials)} thao tác bị từ chối quyền: xem {log_dir.name}/permission_denials.json]").strip()
    approval = None
    if result.subtype == "error_max_budget_usd":  # 2) trong khi chạy: Claude Code tự dừng ở --max-budget-usd
        b_ids = [b["id"] for b in budgets.applicable(con, task) if b["limit_usd"] is not None]
        approval = ("budget", {"reason": f"Chạm ngân sách trong lúc chạy (còn ${remaining_usd or 0:.2f})", "budget_ids": b_ids})
    else:
        rules, calls = tools.ask_hits(result.denials, ask)
        if rules:  # thao tác thuộc nhóm "cần duyệt" bị từ chối → xin phép, chạy lại với quyền được cấp
            approval = ("tool", {"reason": "Agent cần quyền: " + ", ".join(rules), "rules": rules, "calls": calls[:20]})
    target = store.finish(con, task["id"], run_id, worker_id, result.outcome, summary=summary, usage=result.usage,
                          exit_code=result.exit_code, session_id=result.session_id, log_dir=str(log_dir),
                          error=secrets.redact(result.error or "", secret_values) or None,
                          blocked_reason=summary if result.outcome == "blocked" else None, approval=approval)
    budgets.after_run(con, store.get_task(con, task["id"]), actor)  # 3) sau khi chạy: cảnh báo, tự tạm dừng agent
    return task["id"], target


def budget_text(b):
    usd = f"${b['spent_usd']:.2f}/{b['limit_usd']}" if b["limit_usd"] is not None else f"${b['spent_usd']:.2f}"
    tok = f"{b['spent_tokens']:,}/{b['limit_tokens']:,} token" if b["limit_tokens"] is not None else f"{b['spent_tokens']:,} token"
    return f"{budgets.label(b)}: {usd} USD, {tok}"


def loop(con, agent_id, worker_id, base_dir, poll=30, once=False, log=print):
    """Nhịp tim: hết việc thì ngủ `poll` giây rồi xem lại (Phase 4: đánh thức theo sự kiện)."""
    while True:
        res = run_once(con, agent_id, worker_id, base_dir)
        if res:
            log(f"task #{res[0]} → {res[1]}")
            continue
        if once:
            return
        time.sleep(poll)
