"""Phần chung của adapter: chạy tiến trình agent, gia hạn khoá, quá giờ, huỷ cả cây tiến trình."""
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

RESULT_LINE = re.compile(r"^AOS_RESULT:\s*(done|blocked|failed)\b\s*[-:–]?\s*(.*)$", re.I | re.M)


@dataclass
class RunContext:
    task: dict
    project: dict
    agent: dict           # dòng agents + "config"
    prompt: str
    workdir: Path
    env: dict
    log_dir: Path
    timeout_s: int
    heartbeat: callable    # () -> bool; False = mất khoá → dừng agent
    heartbeat_every: int = 30


@dataclass
class AdapterResult:
    exit_code: int | None
    outcome: str            # succeeded | failed | blocked | timeout | cancelled
    summary: str = ""
    usage: dict = field(default_factory=dict)
    session_id: str | None = None
    error: str | None = None
    denials: list = field(default_factory=list)


def kill_tree(proc):
    """Dừng agent và mọi tiến trình con (Claude Code có thể mở shell, node...)."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGINT)  # SIGINT trước: Claude Code kết thúc lượt gọn gàng
            proc.wait(10)
        except Exception:  # noqa: BLE001
            os.killpg(proc.pid, signal.SIGKILL)
    try:
        proc.wait(15)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_process(cmd, ctx: RunContext, stdin_text=""):
    """Chạy cmd trong ctx.workdir; stdout/stderr ghi file trong ctx.log_dir. Trả (exit_code, trạng thái: ok|timeout|cancelled)."""
    ctx.log_dir.mkdir(parents=True, exist_ok=True)
    (ctx.log_dir / "command.json").write_text(json.dumps([str(c) for c in cmd], ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    flags = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" else {"start_new_session": True}
    with open(ctx.log_dir / "stdout.log", "wb") as out, open(ctx.log_dir / "stderr.log", "wb") as err:
        proc = subprocess.Popen([str(c) for c in cmd], cwd=str(ctx.workdir), env=ctx.env, stdin=subprocess.PIPE,
                                stdout=out, stderr=err, **flags)
        try:
            proc.stdin.write(stdin_text.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass
        deadline = time.monotonic() + ctx.timeout_s
        state = "ok"
        while True:
            try:
                proc.wait(timeout=min(ctx.heartbeat_every, max(0.1, deadline - time.monotonic())))
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    state = "timeout"
                elif not ctx.heartbeat():
                    state = "cancelled"
                else:
                    continue
                kill_tree(proc)
                break
    return proc.returncode, state


def read_log(ctx, name, limit=200_000):
    p = ctx.log_dir / name
    if not p.exists():
        return ""
    data = p.read_bytes()[-limit:]
    return data.decode("utf-8", errors="replace")


def parse_result_line(text):
    """Dòng cuối dạng `AOS_RESULT: blocked - lý do` mà prompt yêu cầu agent in ra (tuỳ chọn)."""
    found = RESULT_LINE.findall(text or "")
    return (found[-1][0].lower(), found[-1][1].strip()) if found else (None, "")
