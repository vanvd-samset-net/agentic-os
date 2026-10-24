---
status: draft
updated: 2026-10-24
---

# 01. Kiến trúc

```
                 người (CLI aos)                         agent (tiến trình riêng)
                      │                                         ▲
  ┌───────────────────▼──────────────────────────┐              │ spawn + env riêng
  │                 CONTROL PLANE                 │              │
  │  store.py   : task, khoá, phụ thuộc, góp ý    │      ┌───────┴────────┐
  │  states.py  : máy trạng thái (luật chuyển)    │◄────►│ worker.py      │
  │  audit.py   : nhật ký kiểm toán (ai làm gì)   │      │  adapters/     │
  │  secrets.py : bí mật theo agent               │      │   claude_code  │
  │  config.py  : sơ đồ tổ chức (agents.toml)     │      │   shell        │
  │  usage      : token, chi phí mỗi lần chạy     │      │  workspace.py  │
  └───────────────────┬──────────────────────────┘      └───────┬────────┘
                      ▼                                         ▼
              data/aos.db (SQLite, WAL)              data/runs/<run>/ (prompt, log, result)
                                                     data/worktrees/task-<id>/ (khi dùng worktree)
```

## Thành phần
- **CLI `aos`** (`python -m aos`): người tạo mục tiêu, dự án, task; giao việc; duyệt; xem trạng thái.
- **Control plane** (thư viện Python, một file CSDL SQLite): mọi thay đổi trạng thái đi qua `store.py`, kiểm bằng `states.py`, ghi `audit_log`.
- **Worker** (`aos worker`): vòng lặp "nhịp tim": thu hồi khoá hết hạn → checkout task kế tiếp của agent → dựng ngữ cảnh → chạy adapter → gia hạn khoá trong lúc chạy → ghi kết quả → chuyển trạng thái. Nhiều worker chạy song song an toàn (checkout nguyên tử).
- **Adapter**: lớp nối tới một loại agent. `claude-code` chạy Claude Code CLI không tương tác trong thư mục làm việc của agent; `shell` chạy một lệnh (dùng cho công cụ đơn giản và test).
- **Workspace**: `shared` (thư mục của agent, khoá theo dự án: mỗi dự án tối đa một task chạy) hoặc `worktree` (git worktree riêng cho từng task).

## Luồng một task (Phase 1–2)
1. Người: `aos task add --project lop3d --agent b3b4 --title "Làm site"` → `backlog`; có agent thì `assigned`.
2. Worker của b3b4: checkout nguyên tử → `running` (khoá `lock_owner`, `lock_until`), tạo `runs` mới.
3. Dựng prompt: mục tiêu công ty → dự án → task cha → task → góp ý trước đó (để agent hiểu "vì sao").
4. Adapter chạy agent; worker gia hạn khoá mỗi 30 giây; nhật ký vào `data/runs/<id>/`.
5. Đọc kết quả: mã thoát + JSON kết quả CLI (token, chi phí) + hợp đồng đầu ra của agent (b3b4: `projects/<slug>/output/handoff.json`).
6. Thành công → `under_review`; agent báo chặn → `blocked`; lỗi → thử lại (`assigned`) tới `max_attempts`, rồi `failed`.
7. Người: `aos review <id> --approve` → `done`; `--reject "lý do"` → góp ý được lưu, task về `assigned` để agent làm lại với góp ý trong ngữ cảnh.

## Vì sao tách độc lập
- Mỗi agent giữ luật riêng (AGENTS.md của nó), agentic-os chỉ giao việc và đọc hợp đồng đầu ra → đổi agent không phải sửa bộ điều phối.
- Lỗi của agent không làm hỏng CSDL điều phối (khác tiến trình, khác thư mục).
