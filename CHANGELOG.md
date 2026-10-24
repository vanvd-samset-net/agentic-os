# Changelog

## 0.2.0 (2026-10-24)

- Phase 3: ngân sách token/USD theo công ty, dự án, agent, task (tổng hoặc theo tháng); chặn trước khi chạy (không tính lượt), trong khi chạy (`--max-budget-usd`), sau khi chạy (cảnh báo ngưỡng một lần mỗi kỳ, hết ngân sách agent → tự tạm dừng).
- Phê duyệt: trạng thái `needs_approval`, bảng `approvals`; cổng công cụ allowed/ask/off, quyền được duyệt cấp cho riêng task (`task_grants`). CLI `budget`, `approvals`, `approve`, `deny`, `agent resume|pause`.
- CSDL v2: nâng cấp từ v1 giữ nguyên dữ liệu. `aos init` không bật lại agent đã tự tạm dừng.
- Test: 38/38.

## 0.1.0 (2026-10-24)

- Phase 1: CSDL SQLite, máy trạng thái task, checkout nguyên tử + khoá có hạn + thu hồi, phụ thuộc, góp ý, kiểm toán chỉ thêm, CLI `aos`.
- Phase 2: worker nhịp tim, adapter `claude-code` (Claude Code CLI không tương tác, `dontAsk` + allowedTools) và `shell`, workspace shared/worktree, bí mật theo agent (môi trường tối thiểu, che nhật ký), hợp đồng đầu ra (b3b4 handoff.json), ghi token/chi phí.
- Kiểm bằng 1 lần chạy Claude Code thật (haiku, ~0,0044 USD).
