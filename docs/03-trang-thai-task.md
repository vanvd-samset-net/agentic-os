---
status: draft
updated: 2026-10-24
---

# 03. Máy trạng thái task

```
backlog ──assign──► assigned ──checkout──► running ──thành công──► under_review ──approve──► done
   ▲                  ▲  ▲                   │                        │
   │                  │  └──── retry ────────┤ lỗi (còn lượt)         └──reject (+góp ý)──► assigned
   │                  │                      ├── lỗi (hết lượt) ──► failed ──retry (người)──► assigned
   │                  │                      ├── agent báo chặn ──► blocked ──unblock (người)──► assigned
   │                  └──── recover ─────────┘  (khoá hết hạn: worker chết)
   └── unassign ──────┘
mọi trạng thái chưa kết thúc ──cancel──► cancelled
```

| Từ | Đến | Ai | Điều kiện |
|---|---|---|---|
| `backlog` | `assigned` | người | có agent đang `active` |
| `assigned` | `backlog` | người | bỏ giao |
| `assigned` | `running` | worker | checkout nguyên tử: đúng agent, mọi phụ thuộc `done`, không có task khác đang chạy cùng dự án nếu agent dùng workspace `shared` |
| `running` | `under_review` | worker | adapter thành công và hợp đồng đầu ra báo xong |
| `running` | `blocked` | worker | agent báo việc chặn cần người (b3b4: `handoff.json` = `blocked`) |
| `running` | `assigned` | worker | lỗi, `attempts < max_attempts` |
| `running` | `failed` | worker | lỗi, hết lượt |
| `running` | `assigned` / `failed` | `recover` | khoá hết hạn (worker chết); lần chạy ghi `lost` |
| `under_review` | `done` | người | duyệt |
| `under_review` | `assigned` | người | trả lại; góp ý lưu `task_comments(kind=feedback)` và đưa vào ngữ cảnh lần sau |
| `blocked`, `failed` | `assigned` | người | đã xử lý việc chặn / cho thử lại (đặt lại `attempts`) |
| chưa kết thúc | `cancelled` | người | huỷ |

Trạng thái kết thúc: `done`, `cancelled`.

## Phase 3: `needs_approval`
| Từ | Đến | Ai | Điều kiện |
|---|---|---|---|
| `running` | `needs_approval` | worker | hết ngân sách (trước khi chạy, không tính lượt) / Claude Code dừng ở `--max-budget-usd` / thao tác thuộc nhóm `ask` bị từ chối |
| `needs_approval` | `assigned` | người | duyệt (ngân sách: phải nâng hạn mức cho hết vượt; công cụ: luật được cấp cho riêng task) |
| `needs_approval` | `under_review` | người | từ chối quyền công cụ khi lần chạy trước đã xong |
| `needs_approval` | `failed` | người | từ chối (ngân sách, hoặc lần chạy trước chưa xong) |
