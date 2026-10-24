"""Bí mật theo từng agent (docs/05-bao-mat.md).

- Lưu ở config/secrets/<agent>.env (KEY=VALUE, đã .gitignore), không trong CSDL, không trong agents.toml.
- Chỉ nạp những tên agent khai báo trong `secrets = [...]`, chỉ vào tiến trình của agent đó.
- Tiến trình agent nhận môi trường tối thiểu (không thừa hưởng toàn bộ biến của người chạy worker).
- Nhật ký chạy được che giá trị bí mật trước khi lưu lâu dài.
"""
import os
from pathlib import Path

from .db import ROOT

SECRETS_DIR = Path(os.environ.get("AOS_SECRETS_DIR") or ROOT / "config" / "secrets")

# Biến hệ thống cần để chương trình chạy được trên Windows/Unix (không chứa bí mật).
BASE_ENV = (
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR", "HOME",
    "USERPROFILE", "USERNAME", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "COMMONPROGRAMFILES", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS", "LANG",
    "LC_ALL", "TERM",
)


def read_env_file(path):
    out = {}
    if not Path(path).exists():
        return out
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_for(agent_id, names):
    """{tên: giá trị} cho đúng các tên agent được cấp. Thiếu tên → lỗi (không chạy agent thiếu quyền truy cập)."""
    if not names:
        return {}
    available = read_env_file(SECRETS_DIR / f"{agent_id}.env")
    missing = [n for n in names if n not in available]
    if missing:
        raise KeyError(f"Thiếu bí mật cho agent {agent_id}: {', '.join(missing)} (config/secrets/{agent_id}.env)")
    return {n: available[n] for n in names}


def build_env(agent_env, secret_values, parent=None):
    parent = os.environ if parent is None else parent
    upper = {k.upper(): k for k in parent}
    env = {upper[k]: parent[upper[k]] for k in BASE_ENV if k in upper}
    env.update({k: str(v) for k, v in (agent_env or {}).items()})
    env.update(secret_values or {})
    env["PYTHONIOENCODING"] = env.get("PYTHONIOENCODING", "utf-8")
    return env


def redact(text, secret_values):
    for v in sorted((v for v in (secret_values or {}).values() if len(v) >= 4), key=len, reverse=True):
        text = text.replace(v, "***")
    return text


def redact_files(paths, secret_values):
    if not secret_values:
        return
    for p in paths:
        p = Path(p)
        if p.exists():
            raw = p.read_text(encoding="utf-8", errors="replace")
            clean = redact(raw, secret_values)
            if clean != raw:
                p.write_text(clean, encoding="utf-8")
