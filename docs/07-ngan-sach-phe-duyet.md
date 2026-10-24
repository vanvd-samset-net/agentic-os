---
status: draft
updated: 2026-10-24
---

# 07. Ngân sách và phê duyệt (Phase 3)

## Ngân sách (`budgets`)
| Cột | Ý nghĩa |
|---|---|
| `scope` | `org` \| `project` \| `agent` \| `task` |
| `scope_id` | `''` (org), slug dự án, id agent, id task |
| `period` | `total` (cộng dồn mãi) \| `month` (tháng hiện tại, UTC) |
| `limit_usd`, `limit_tokens` | Hạn mức (để trống = không giới hạn theo đơn vị đó). Token = vào + ra + ghi cache + đọc cache |
| `warn_ratio` | Mặc định 0,8: vượt ngưỡng này thì cảnh báo |

Chi tiêu = tổng `runs` thuộc phạm vi (theo kỳ). Chi phí USD là **ước tính** của Claude Code, không phải hoá đơn.

### Chặn ở 3 chỗ
1. **Trước khi chạy** (sau checkout): ngân sách nào áp cho task đã hết → không chạy agent; lần chạy `cancelled`, task → `needs_approval` (yêu cầu loại `budget`), không tính lượt thử.
2. **Trong khi chạy**: truyền `--max-budget-usd <phần còn lại nhỏ nhất>` cho Claude Code; CLI tự dừng khi chạm (`error_max_budget_usd`) → task → `needs_approval`.
3. **Sau khi chạy**: ghi chi tiêu; vượt `warn_ratio` lần đầu → kiểm toán `budget.warn` + ghi chú vào task; vượt 100% ngân sách **agent** → agent tự `paused` (không nhận task mới tới khi người bật lại).

## Phê duyệt (`approvals`)
| Cột | Ý nghĩa |
|---|---|
| `kind` | `budget` \| `tool` |
| `status` | `pending` \| `approved` \| `denied` |
| `request_json` | Lý do, ngân sách đã chạm / thao tác bị từ chối, kết quả lần chạy |
| `decided_by`, `decision_note` | Người quyết, ghi chú |

### Cổng công cụ 3 mức (cấu hình agent)
```toml
[agents.b3b4.tools]
allowed = ["Read", "Edit", "Bash(python *)"]   # tự chạy
ask     = ["Bash(git commit *)", "WebFetch"]    # cần người duyệt: lần đầu bị từ chối → yêu cầu phê duyệt
off     = ["Bash(git push *)", "Bash(rm -rf *)"] # cấm hẳn
```
Ánh xạ sang Claude Code: `allowed` (+ quyền đã được duyệt cho task) → `--allowedTools`; `off` → `--disallowedTools`; `ask` không truyền → bị từ chối ở chế độ `dontAsk` và nằm trong `permission_denials`.
Sau lần chạy, thao tác bị từ chối khớp một luật `ask` → yêu cầu `tool` (pending), task → `needs_approval`. Duyệt → luật được cấp **cho riêng task đó** (`task_grants`), task → `assigned`, lần chạy sau có quyền. Từ chối → task về `under_review` (lần chạy trước đã xong) hoặc `failed`.

### Trạng thái mới
`running → needs_approval` (worker); `needs_approval → assigned` (duyệt), `→ under_review | failed` (từ chối), `→ cancelled`.

## CLI
```
aos budget set --scope agent --id b3b4 --usd 5 --tokens 3000000 [--period month] [--warn 0.8]
aos budget list                       # hạn mức, đã dùng, %
aos approvals [--all]                 # yêu cầu đang chờ
aos approve <id> [--raise-usd 3] [--raise-tokens N] [--note ...]
aos deny <id> --note "..."
aos agent resume <id>                 # bật lại agent bị tự dừng vì hết ngân sách
```
