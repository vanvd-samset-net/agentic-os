---
status: proposed
---

# ADR-001 Python thư viện chuẩn + SQLite

## Bối cảnh
Bộ điều phối chạy trên máy Windows của người dùng (và có thể trên server OpenHands), điều phối vài agent, vài chục task một lúc. Agent hiện có (b3b4) đều là script Python thư viện chuẩn.

## Các phương án
### Phương án A: Python 3.11+ thư viện chuẩn + SQLite (WAL)
- Ưu: không cài gì; một file CSDL; `BEGIN IMMEDIATE` cho checkout nguyên tử giữa nhiều worker; dễ sao lưu.
- Nhược: một máy; ghi đồng thời bị tuần tự hoá (đủ cho vài chục worker).
### Phương án B: Node/TypeScript + Postgres (như Paperclip)
- Ưu: nhiều máy, nhiều người dùng.
- Nhược: phải cài và vận hành Postgres; nặng so với nhu cầu hiện tại.
### Phương án C: Hàng đợi có sẵn (Redis/RQ, Celery)
- Nhược: thêm dịch vụ; vẫn cần CSDL cho mục tiêu, kiểm toán.

## Quyết định
Chọn **A**. Lớp `store.py` gom mọi truy cập CSDL để sau này đổi sang Postgres không phải sửa worker/adapter.

## Hệ quả
- Chạy ngay bằng `python -m aos`. Khi cần nhiều máy: thay `db.py` + câu SQL đặc thù SQLite (`BEGIN IMMEDIATE`).

[KHÔNG CẦN TRA CỨU: chỉ dùng thư viện chuẩn Python 3.12 đã có trên máy]
