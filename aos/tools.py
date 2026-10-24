"""Cổng công cụ 3 mức (docs/07): allowed (tự chạy) / ask (cần người duyệt) / off (cấm).

Luật theo cú pháp Claude Code: `Tên` hoặc `Tên(mẫu)`, ví dụ `Read`, `Bash(git commit *)`, `WebFetch`.
Với Bash: `*` khớp bất kỳ; dấu cách trước `*` cuối có nghĩa ("git commit *" khớp "git commit" và "git commit -m x",
không khớp "git commitx").
"""
import fnmatch
import re

RULE = re.compile(r"^([A-Za-z_][\w-]*)(?:\((.*)\))?$")


def policy(agent_cfg, granted=()):
    """(allowed, ask, off). Tương thích cấu hình cũ claude.allowed_tools / disallowed_tools."""
    t = agent_cfg.get("tools") or {}
    cc = agent_cfg.get("claude") or {}
    allowed = list(t.get("allowed") or cc.get("allowed_tools") or [])
    off = list(t.get("off") or cc.get("disallowed_tools") or [])
    ask = [r for r in (t.get("ask") or []) if r not in granted]
    allowed += [g for g in granted if g not in allowed]
    return allowed, ask, off


def _command(tool_input):
    if isinstance(tool_input, dict):
        return str(tool_input.get("command") or tool_input.get("url") or tool_input.get("file_path") or "")
    return str(tool_input or "")


def rule_matches(rule, tool_name, tool_input):
    m = RULE.match(rule.strip())
    if not m or m.group(1) != tool_name:
        return False
    pattern = m.group(2)
    if pattern is None or pattern == "*":
        return True
    cmd = _command(tool_input).strip()
    if pattern.endswith(":*"):  # cú pháp cũ "git log:*" = "git log *"
        pattern = pattern[:-2] + " *"
    if pattern.endswith(" *") and cmd == pattern[:-2]:
        return True
    return fnmatch.fnmatchcase(cmd, pattern)


def ask_hits(denials, ask_rules):
    """Luật `ask` khớp các thao tác bị từ chối → (luật cần duyệt, các thao tác tương ứng)."""
    rules, calls = [], []
    for d in denials or []:
        name = d.get("tool_name") or d.get("toolName") or d.get("name") or ""
        inp = d.get("tool_input") or d.get("toolInput") or d.get("input") or {}
        for rule in ask_rules:
            if rule_matches(rule, name, inp):
                if rule not in rules:
                    rules.append(rule)
                calls.append({"tool": name, "input": _command(inp)[:300], "rule": rule})
                break
    return rules, calls
