---
status: draft
updated: 2026-10-24
---

# 05. Bảo mật

| Rủi ro | Biện pháp (Phase 1–2) | Phase sau |
|---|---|---|
| Agent chạy không người trực làm việc nguy hiểm | Claude Code chạy `--permission-mode dontAsk` + `allowedTools` tối thiểu theo agent + `disallowedTools` (vd `git push`, `rm -rf`, `WebFetch`); thao tác ngoài danh sách bị từ chối và được ghi lại. **Cấm** `bypassPermissions` / `--dangerously-skip-permissions` (cấu hình bị từ chối khi nạp) | Phase 3: thao tác bị từ chối → yêu cầu phê duyệt (`needs_approval`), người duyệt cấp quyền cho lần chạy lại |
| Lộ bí mật | Bí mật ở `config/secrets/<agent>.env` (gitignore); chỉ tên được khai trong `secrets = [...]` mới nạp, chỉ vào tiến trình của agent đó; thiếu bí mật thì không chạy agent; nhật ký được che (`***`); không ghi vào CSDL/kiểm toán | Kho bí mật của hệ điều hành / vault |
| Agent đọc bí mật của người chạy worker | Môi trường tối thiểu (PATH, thư mục hệ thống...) thay vì thừa hưởng toàn bộ biến | |
| Hai agent ghi đè nhau | Checkout nguyên tử, khoá có hạn, mỗi dự án một task chạy (workspace `shared`) hoặc worktree riêng | |
| Agent treo / chạy mãi | `timeout_min`, `max_turns`; dừng cả cây tiến trình | Hạn mức token/USD (Phase 3) |
| Không truy được ai làm gì | `audit_log` chỉ thêm (trigger chặn sửa/xoá); mọi chuyển trạng thái ghi tác nhân `human:`/`worker:`/`system` | Ký số nhật ký |
| Agent tự duyệt việc của mình | Máy trạng thái: chỉ `human` được `under_review → done`; worker không được | Phase 4: lead agent duyệt có giới hạn |
| Prompt injection từ đầu vào khách | Luật của từng agent (b3b4: đầu vào là dữ liệu) + quyền công cụ hẹp; agentic-os không đưa nội dung file khách vào prompt, chỉ đưa task/góp ý | |
| Tự cập nhật CLI giữa lần chạy | `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` cho tiến trình agent | Ghim phiên bản CLI |
