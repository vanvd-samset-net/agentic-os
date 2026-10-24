"""Sơ đồ tổ chức: config/agents.toml → bảng agents (docs/04-worker-adapter.md)."""
import os
import tomllib
from pathlib import Path

from .db import ROOT

CONFIG = Path(os.environ.get("AOS_CONFIG") or ROOT / "config" / "agents.toml")
ADAPTERS = {"claude-code", "shell"}
FORBIDDEN_MODES = {"bypassPermissions"}
FORBIDDEN_ARGS = {"--dangerously-skip-permissions", "--allow-dangerously-skip-permissions"}


class ConfigError(ValueError):
    pass


def load(path=None):
    p = Path(path or CONFIG)
    if not p.exists():
        raise ConfigError(f"Chưa có {p}. Chép config/agents.example.toml thành config/agents.toml rồi sửa.")
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    agents = data.get("agents") or {}
    for aid, a in agents.items():
        validate(aid, a)
    return {"org": data.get("org") or {}, "agents": agents, "base_dir": p.parent.parent}


def validate(aid, a):
    if a.get("adapter") not in ADAPTERS:
        raise ConfigError(f"agents.{aid}.adapter phải là một trong {sorted(ADAPTERS)}")
    if a.get("workspace", "shared") not in ("shared", "worktree"):
        raise ConfigError(f"agents.{aid}.workspace phải là shared hoặc worktree")
    if not a.get("workdir"):
        raise ConfigError(f"agents.{aid}.workdir bắt buộc (thư mục làm việc của agent)")
    cc = a.get("claude") or {}
    if cc.get("permission_mode") in FORBIDDEN_MODES:
        raise ConfigError(f"agents.{aid}: không cho phép permission_mode {cc['permission_mode']} (chạy không người giám sát)")
    if FORBIDDEN_ARGS & set(cc.get("extra_args") or []):
        raise ConfigError(f"agents.{aid}: không cho phép bỏ qua kiểm tra quyền")
    for key in ("secrets",):
        if any(not str(s).replace("_", "").isalnum() for s in a.get(key) or []):
            raise ConfigError(f"agents.{aid}.{key}: tên biến chỉ gồm chữ, số, _")


def sync(con, cfg, actor="system"):
    """Ghi tổ chức + agent vào CSDL. Không ghi bí mật (chỉ tên biến)."""
    from . import store
    org = cfg["org"]
    store.ensure_org(con, org.get("name", "Công ty"), org.get("mission", ""), actor=actor)
    for aid, a in cfg["agents"].items():
        store.upsert_agent(con, aid, a.get("name", aid), a["adapter"], role=a.get("role", ""),
                           reports_to=a.get("reports_to"), config=a, status=a.get("status", "active"), actor=actor)
    return sorted(cfg["agents"])
