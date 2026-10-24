---
status: proposed
---

# ADR-002 Gọi agent bằng Claude Code CLI không tương tác

## Bối cảnh
Agent của pipeline (b3b4) được viết để chạy trong Claude Code (AGENTS.md, skill, script). Bộ điều phối cần chạy chúng không người trực, đo token, giới hạn quyền.

## Các phương án
### Phương án A: `claude -p` + `--output-format json` + `--permission-mode dontAsk` + `allowedTools`
- Ưu: agent giữ nguyên luật, skill, CLAUDE.md của nó; có token, chi phí, session, danh sách thao tác bị từ chối; quyền hẹp theo agent.
- Nhược: phụ thuộc phiên bản CLI; chi phí là ước tính.
### Phương án B: Claude Agent SDK (Python) trong cùng tiến trình
- Ưu: điều khiển chi tiết (canUseTool để phê duyệt từng thao tác).
- Nhược: chạy trong tiến trình bộ điều phối (agent lỗi kéo theo bộ điều phối); thêm phụ thuộc.
### Phương án C: `--dangerously-skip-permissions` cho nhanh
- Nhược: agent làm được mọi thứ trên máy người dùng. **Loại.**

## Quyết định
Chọn **A**; cấu hình chặn mọi chế độ bỏ qua kiểm tra quyền. Phase 3 xem xét B cho bước phê duyệt từng thao tác.

## Hệ quả
- Phải giữ `allowed_tools` của từng agent đủ dùng: xem `permission_denials.json` sau lần chạy đầu để chỉnh.
- Prompt dài đi qua stdin (Windows giới hạn ~8191 ký tự dòng lệnh).

[NGUỒN: https://code.claude.com/docs/en/headless.md, https://code.claude.com/docs/en/permission-modes.md, https://code.claude.com/docs/en/cli-reference.md, 2026-10-24]
