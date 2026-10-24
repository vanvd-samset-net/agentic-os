---
status: proposed
---

# ADR-003 Cô lập thư mục làm việc

## Bối cảnh
b3b4 giữ mọi dự án trong `projects/<slug>/` của chính repo, script đọc `WP_AGENT_PROJECT`. Agent khác (sửa code repo) cần nhánh riêng để người duyệt xem diff.

## Các phương án
### Phương án A: `shared` + khoá theo dự án
- Ưu: đúng cách b3b4 đang chạy (site Docker/Local gắn với thư mục dự án); không nhân bản dữ liệu lớn (site, ảnh).
- Nhược: hai task cùng dự án không chạy song song.
### Phương án B: git worktree mỗi task
- Ưu: cô lập file, có diff để duyệt.
- Nhược: dữ liệu lớn không nằm trong git (site, node_modules) phải dựng lại.
### Phương án C: container/sandbox từ xa (e2b, Modal)
- Nhược: chi phí, cấu hình; để sau.

## Quyết định
Hỗ trợ **A và B**, chọn theo agent (`workspace = "shared" | "worktree"`). b3b4 dùng A.

## Hệ quả
Checkout với `shared` kiểm "dự án không có task khác đang chạy". Worktree dọn ở Phase 3.

[KHÔNG CẦN TRA CỨU: dùng git worktree có sẵn]
