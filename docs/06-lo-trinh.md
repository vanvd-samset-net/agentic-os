---
status: draft
updated: 2026-10-24
---

# 06. Lộ trình

| Phase | Nội dung | Trạng thái | Tiêu chí xong |
|---|---|---|---|
| 1 | CSDL, máy trạng thái, checkout nguyên tử + khoá có hạn + thu hồi, phụ thuộc, góp ý, kiểm toán chỉ thêm, CLI | **Xong (2026-10-24)** | `tests/test_store.py` 14/14 |
| 2 | Worker nhịp tim, adapter `claude-code` + `shell`, workspace `shared`/`worktree`, bí mật theo agent, hợp đồng đầu ra, ghi token/chi phí | **Xong (2026-10-24)** | `tests/test_worker.py` 13/13; 1 lần chạy Claude Code thật qua `aos worker` |
| 3 | Quản trị và ngân sách (`docs/07`): `budgets` (công ty/dự án/agent/task, token + USD, tổng hoặc theo tháng), chặn trước/trong (`--max-budget-usd`)/sau khi chạy, cảnh báo ngưỡng, tự `pause` agent; `approvals` + `needs_approval`; cổng công cụ allowed/ask/off, quyền cấp theo task; CSDL v2 (nâng cấp giữ dữ liệu) | **Xong (2026-10-24)** | `tests/test_phase3.py` 11/11. Còn lại: dọn worktree khi `done` |
| 4 | Giao việc giữa agent: agent ghi `handoff` có `next_tasks` → tạo task con cho agent kế (B3B4 → B5 → B6) kèm đường dẫn sản phẩm; lịch định kỳ (cron) và đánh thức theo sự kiện thay cho chờ `poll`; giao diện web (tận dụng bảng điều khiển của b3b4) | Chưa | Pipeline B3B4 → B5 chạy nối tiếp không cần người tạo task tay |

## Việc nên làm ngay trước Phase 3
- Chạy thử một task b3b4 thật qua agentic-os trên một dự án nhỏ, xem `permission_denials` để chỉnh `allowed_tools` cho vừa.
- Cài Claude Code bản native (đường dẫn ổn định) thay cho bản đi kèm VS Code.
