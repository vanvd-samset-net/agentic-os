"""Adapter `shell`: chạy một lệnh cố định (công cụ đơn giản, test). Prompt đưa vào stdin.

Cấu hình: [agents.<id>.shell] command = ["python", "tools/x.py", "{task_id}", "{project_slug}"]
Thành công khi mã thoát 0; dòng `AOS_RESULT: blocked|failed - ...` trong stdout ghi đè kết quả.
"""
from .base import AdapterResult, parse_result_line, read_log, run_process


def run(ctx):
    cfg = ctx.agent["config"].get("shell") or {}
    values = {"{task_id}": ctx.task["id"], "{project_slug}": ctx.project["slug"], "{workdir}": ctx.workdir}
    cmd = []
    for part in cfg.get("command") or []:  # chỉ thay đúng các chỗ điền (lệnh có thể chứa { } thật, ví dụ JSON)
        part = str(part)
        for k, v in values.items():
            part = part.replace(k, str(v))
        cmd.append(part)
    if not cmd:
        return AdapterResult(None, "failed", error="Thiếu agents.<id>.shell.command")
    code, state = run_process(cmd, ctx, stdin_text=ctx.prompt)
    out = read_log(ctx, "stdout.log")
    if state != "ok":
        return AdapterResult(code, state, error=f"Agent bị dừng: {state}")
    status, note = parse_result_line(out)
    summary = note or out.strip()[-1500:]
    if status == "blocked":
        return AdapterResult(code, "blocked", summary=summary)
    if code != 0 or status == "failed":
        return AdapterResult(code, "failed", summary=summary, error=read_log(ctx, "stderr.log")[-1500:] or summary)
    return AdapterResult(code, "succeeded", summary=summary)
