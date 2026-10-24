---
status: draft
updated: 2026-10-24
---

# 00. Tổng quan: agentic-os

Bộ điều phối ("công ty") cho các agent ("nhân viên") của pipeline làm website: B1 SRS → B2 Layout → B3+B4 (`b3b4-wordpress-agent`) → B5 Test → B6 Deploy. Học theo mô hình Paperclip (tài liệu `agentic_os_paperclip_guide.md` người dùng gửi ngày 2026-10-24).

## Mục tiêu
1. **Giao việc theo task, không theo câu lệnh**: mỗi việc là một task có mục tiêu, dự án, người nhận (agent), trạng thái, lịch sử.
2. **Một task chỉ một agent làm tại một thời điểm** (checkout có khoá, có hạn), không hai agent ghi đè cùng dự án.
3. **Biết agent làm gì, tốn bao nhiêu**: mỗi lần chạy lưu nhật ký, kết quả, token, chi phí.
4. **Người duyệt trước khi chốt**: task xong chuyển "chờ duyệt"; người duyệt chấp nhận hoặc trả lại kèm góp ý.
5. **Agent độc lập**: agentic-os không chứa code của agent nào; gọi agent qua CLI như gọi công cụ, đọc kết quả qua hợp đồng đầu ra (ví dụ `handoff.json` của b3b4).

## Phạm vi lần này (Phase 1–2)

| Có | Chưa (Phase 3–4) |
|---|---|
| CSDL SQLite: tổ chức, agent, mục tiêu, dự án, task, phụ thuộc, lần chạy, góp ý, nhật ký kiểm toán | Chặn khi vượt ngân sách, phê duyệt công cụ nguy hiểm |
| Máy trạng thái task, checkout nguyên tử + khoá có hạn + gia hạn + thu hồi khi agent chết | Agent A tự tạo task con giao agent B kèm sản phẩm |
| Worker chạy agent bằng adapter `claude-code` (Claude Code CLI không tương tác) và `shell` | Lịch định kỳ (cron), đánh thức theo sự kiện |
| Bí mật theo từng agent, chỉ nạp vào tiến trình của agent đó, che trong nhật ký | Giao diện web |
| Ghi token/chi phí mỗi lần chạy | Nhiều nhà cung cấp mô hình (Codex, webhook) |
| CLI `aos` | |

## Không làm
- Không sửa, không chứa code của b3b4 hay agent khác.
- Không chạy lệnh vào site thật (theo luật của từng agent; agentic-os chỉ giao việc).
- Không gửi dữ liệu ra dịch vụ ngoài ngoài lời gọi mô hình của chính agent.

## Tài liệu
| File | Nội dung |
|---|---|
| `01-kien-truc.md` | Thành phần, luồng chạy |
| `02-du-lieu.md` | Bảng CSDL |
| `03-trang-thai-task.md` | Máy trạng thái, ai chuyển trạng thái nào |
| `04-worker-adapter.md` | Worker, khoá, adapter, workspace, hợp đồng kết quả |
| `05-bao-mat.md` | Bí mật, quyền công cụ, kiểm toán |
| `06-lo-trinh.md` | Phase 1–4, tiêu chí xong |
| `adr/` | Quyết định kiến trúc |
