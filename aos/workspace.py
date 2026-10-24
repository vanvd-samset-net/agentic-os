"""Thư mục làm việc cho từng lần chạy (docs/04-worker-adapter.md, ADR-003)."""
import subprocess
from pathlib import Path

from . import db


class WorkspaceError(RuntimeError):
    pass


def prepare(agent_cfg, task):
    """shared: chạy trong thư mục của agent (khoá theo dự án ở checkout).
    worktree: git worktree riêng data/worktrees/task-<id> trên nhánh aos/task-<id> (tạo nếu chưa có, dùng lại khi làm lại)."""
    workdir = Path(agent_cfg["workdir"])
    if not workdir.is_dir():
        raise WorkspaceError(f"Không có thư mục làm việc {workdir}")
    if agent_cfg.get("workspace", "shared") == "shared":
        return workdir
    target = db.DATA / "worktrees" / f"task-{task['id']}"
    if (target / ".git").exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    branch = f"aos/task-{task['id']}"
    exists = subprocess.run(["git", "-C", str(workdir), "rev-parse", "--verify", "--quiet", branch],
                            capture_output=True).returncode == 0
    cmd = ["git", "-C", str(workdir), "worktree", "add", str(target)] + ([branch] if exists else ["-b", branch])
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise WorkspaceError("Không tạo được git worktree: " + (r.stderr or r.stdout).strip()[:400])
    return target
