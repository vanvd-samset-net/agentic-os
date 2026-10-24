"""Adapter `claude-code`: chạy Claude Code CLI không tương tác (ADR-002).

Lệnh: claude -p --output-format json --permission-mode <dontAsk> --allowedTools ... [--disallowedTools ...]
      [--max-turns N] [--model M] [--append-system-prompt ...]  < prompt (qua stdin, tránh giới hạn độ dài dòng lệnh Windows)
- dontAsk: thao tác cần xin phép mà không nằm trong allowedTools bị từ chối, lần chạy vẫn tiếp tục;
  danh sách bị từ chối nằm ở `permission_denials` của kết quả (Phase 3: chuyển thành yêu cầu phê duyệt).
- Không bao giờ dùng bypassPermissions / --dangerously-skip-permissions (config.validate chặn).
- total_cost_usd là ước tính phía máy khách, không phải hoá đơn.
"""
import glob
import json
import os
import shutil
from pathlib import Path

from .base import AdapterResult, parse_result_line, read_log, run_process

SYSTEM_NOTE = ("Bạn đang chạy không có người trực (agentic-os giao việc). Không hỏi lại qua chat; việc cần người quyết "
               "thì ghi vào tài liệu theo luật của dự án rồi làm tiếp phần làm được. Dòng cuối cùng của câu trả lời: "
               "`AOS_RESULT: done|blocked|failed - <tóm tắt một câu>`.")


def find_cli(configured=""):
    """Lệnh claude CLI (danh sách): cấu hình → PATH → bản cài native → bản đi kèm extension VS Code (mới nhất, dự phòng)."""
    if isinstance(configured, list) and configured:
        return [str(c) for c in configured]
    return [_find_exe(configured)]


def _find_exe(configured=""):
    if configured:
        if Path(configured).exists() or shutil.which(configured):
            return configured
        raise FileNotFoundError(f"Không thấy claude CLI tại {configured}")
    for cand in (shutil.which("claude"), str(Path.home() / ".local" / "bin" / "claude.exe"),
                 str(Path.home() / ".local" / "bin" / "claude")):
        if cand and Path(cand).exists() and not cand.lower().endswith(".cmd"):
            return cand
    bundled = sorted(glob.glob(str(Path.home() / ".vscode" / "extensions" / "anthropic.claude-code-*" / "resources"
                                   / "native-binary" / "claude*")))
    bundled = [b for b in bundled if Path(b).suffix.lower() in ("", ".exe")]
    if bundled:
        return bundled[-1]
    raise FileNotFoundError("Không thấy claude CLI. Cài Claude Code (native) hoặc đặt agents.<id>.claude.command.")


def build_command(cfg, exe, allowed=(), off=(), max_budget_usd=None):
    cmd = [*exe, "-p", "--output-format", "json", "--permission-mode", cfg.get("permission_mode", "dontAsk")]
    if allowed:
        cmd += ["--allowedTools", ",".join(allowed)]
    if off:
        cmd += ["--disallowedTools", ",".join(off)]
    if max_budget_usd is not None:
        cmd += ["--max-budget-usd", f"{max(0.01, max_budget_usd):.4f}"]
    if cfg.get("max_turns"):
        cmd += ["--max-turns", str(int(cfg["max_turns"]))]
    if cfg.get("model"):
        cmd += ["--model", cfg["model"]]
    cmd += ["--append-system-prompt", SYSTEM_NOTE + tools_note(allowed, off)
            + (" " + cfg["append_system_prompt"] if cfg.get("append_system_prompt") else "")]
    return cmd + list(cfg.get("extra_args") or [])


def tools_note(allowed, off):
    """Cho agent biết quyền của nó. Lần chạy thử đầu (2026-10-24): một lệnh nối `echo … && ls …` bị từ chối,
    agent tưởng Bash bị cấm hẳn và bỏ luôn các lệnh được phép."""
    if not allowed and not off:
        return ""
    parts = [" Quyền công cụ của bạn trong lần chạy này:"]
    if allowed:
        parts.append(" được phép: " + ", ".join(allowed) + ".")
    if off:
        parts.append(" cấm: " + ", ".join(off) + ".")
    parts.append(" Mỗi lệnh Bash là một lệnh đơn khớp danh sách (Claude Code tách lệnh nối bằng && ; | và kiểm từng phần);"
                 " một lệnh bị từ chối không có nghĩa mọi lệnh Bash bị cấm, hãy thử lệnh đơn được phép."
                 " Thao tác ngoài danh sách sẽ bị từ chối và được ghi lại để người quản lý cấp quyền nếu cần.")
    return "".join(parts)


def parse_json_result(stdout):
    """Đối tượng JSON cuối cùng trong stdout (output-format json in một đối tượng kết quả)."""
    text = stdout.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def usage_from(res):
    """Token + chi phí. Ưu tiên modelUsage (gồm cả subagent) nếu có, không thì usage (vòng chính)."""
    out = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
    model_usage = res.get("modelUsage") or res.get("model_usage")
    if isinstance(model_usage, dict) and model_usage:
        for m in model_usage.values():
            out["input_tokens"] += int(m.get("inputTokens", m.get("input_tokens", 0)) or 0)
            out["output_tokens"] += int(m.get("outputTokens", m.get("output_tokens", 0)) or 0)
            out["cache_read_tokens"] += int(m.get("cacheReadInputTokens", m.get("cache_read_input_tokens", 0)) or 0)
            out["cache_write_tokens"] += int(m.get("cacheCreationInputTokens", m.get("cache_creation_input_tokens", 0)) or 0)
    else:
        u = res.get("usage") or {}
        out = {"input_tokens": int(u.get("input_tokens", 0) or 0), "output_tokens": int(u.get("output_tokens", 0) or 0),
               "cache_read_tokens": int(u.get("cache_read_input_tokens", 0) or 0),
               "cache_write_tokens": int(u.get("cache_creation_input_tokens", 0) or 0)}
    out["cost_usd"] = float(res.get("total_cost_usd") or 0)
    out["num_turns"] = res.get("num_turns")
    return out


def run(ctx):
    cfg = ctx.agent["config"].get("claude") or {}
    try:
        exe = find_cli(cfg.get("command", ""))
    except FileNotFoundError as e:
        return AdapterResult(None, "failed", error=str(e))
    env = dict(ctx.env)
    env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")  # không tự cập nhật/telemetry giữa lúc chạy
    ctx.env = env
    code, state = run_process(build_command(cfg, exe, ctx.allowed_tools, ctx.off_tools, ctx.max_budget_usd), ctx,
                              stdin_text=ctx.prompt)
    stdout = read_log(ctx, "stdout.log", limit=5_000_000)
    res = parse_json_result(stdout) or {}
    if res:
        (ctx.log_dir / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    usage = usage_from(res) if res else {}
    denials = res.get("permission_denials") or []
    common = {"usage": usage, "session_id": res.get("session_id"), "denials": denials, "subtype": res.get("subtype")}
    if state != "ok":
        return AdapterResult(code, state, error=f"Agent bị dừng: {state}", **common)
    text = res.get("result") or ""
    status, note = parse_result_line(text)
    summary = note or text.strip()[-1500:]
    if not res:
        return AdapterResult(code, "failed", error="Không đọc được kết quả JSON của Claude Code. "
                             + read_log(ctx, "stderr.log")[-800:], **common)
    if res.get("is_error") or code != 0:
        return AdapterResult(code, "failed", summary=summary,
                             error=f"{res.get('subtype', 'error')}: {(text or read_log(ctx, 'stderr.log'))[-800:]}", **common)
    if status == "blocked":
        return AdapterResult(code, "blocked", summary=summary, **common)
    if status == "failed":
        return AdapterResult(code, "failed", summary=summary, error=summary, **common)
    return AdapterResult(code, "succeeded", summary=summary, **common)
