# agentic-os: luật cho agent sửa repo này

- Đọc `docs/` trước khi sửa; đổi hành vi thì sửa tài liệu cùng lúc.
- Chỉ thư viện chuẩn Python 3.11+. Mọi truy cập CSDL qua `aos/store.py`; mọi chuyển trạng thái qua `store._set_status` (kiểm bằng `states.py`, ghi `audit_log` cùng giao dịch).
- Không bao giờ: thêm `bypassPermissions` / `--dangerously-skip-permissions`; ghi bí mật vào CSDL, kiểm toán, nhật ký; cho tiến trình agent thừa hưởng toàn bộ môi trường; cho worker chuyển task sang `done`.
- Không chứa code của agent khác (b3b4...). Tích hợp qua cấu hình (`config/agents.toml`) và hợp đồng đầu ra.
- Mọi thay đổi có test trong `tests/`; chạy `python -m unittest discover tests` trước khi báo xong. Test không gọi mô hình thật.
- Giải thích cho người dùng bằng tiếng Việt ngắn gọn.
