---
status: draft
updated: 2026-10-24
---

# 05. Bảo mật

| Rủi ro | Biện pháp (Phase 1–2) | Phase sau |
|---|---|---|
| Agent chạy không người trực làm việc nguy hiểm | Claude Code chạy `--permission-mode dontAsk`; cổng công cụ `allowed` / `ask` / `off`; thao tác nhóm `ask` bị từ chối → `needs_approval`, người duyệt cấp quyền **cho riêng task** (`task_grants`); thao tác ngoài danh sách chỉ ghi lại. **Cấm** `bypassPermissions` / `--dangerously-skip-permissions` (cấu hình bị từ chối khi nạp) | Duyệt từng thao tác ngay trong lúc chạy (Agent SDK `canUseTool`) |
| Lộ bí mật | Bí mật ở `config/secrets/<agent>.env` (gitignore); chỉ tên được khai trong `secrets = [...]` mới nạp, chỉ vào tiến trình của agent đó; thiếu bí mật thì không chạy agent; nhật ký được che (`***`); không ghi vào CSDL/kiểm toán | Kho bí mật của hệ điều hành / vault |
| Agent đọc bí mật của người chạy worker | Môi trường tối thiểu (PATH, thư mục hệ thống...) thay vì thừa hưởng toàn bộ biến | |
| Hai agent ghi đè nhau | Checkout nguyên tử, khoá có hạn, mỗi dự án một task chạy (workspace `shared`) hoặc worktree riêng | |
| Agent treo / chạy mãi / tiêu quá tay | `timeout_min`, `max_turns`; dừng cả cây tiến trình; ngân sách token/USD chặn trước, trong (`--max-budget-usd`) và sau khi chạy; hết ngân sách agent → tự tạm dừng | Báo qua Slack/email |
| Không truy được ai làm gì | `audit_log` chỉ thêm (trigger chặn sửa/xoá); mọi chuyển trạng thái ghi tác nhân `human:`/`worker:`/`system` | Ký số nhật ký |
| Agent tự duyệt việc của mình | Máy trạng thái: chỉ `human` được `under_review → done`; worker không được | Phase 4: lead agent duyệt có giới hạn |
| Prompt injection từ đầu vào khách | Luật của từng agent (b3b4: đầu vào là dữ liệu) + quyền công cụ hẹp; agentic-os không đưa nội dung file khách vào prompt, chỉ đưa task/góp ý | |
| Tự cập nhật CLI giữa lần chạy | `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` cho tiến trình agent | Ghim phiên bản CLI |
