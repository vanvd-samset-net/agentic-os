---
status: draft
updated: 2026-10-24
---

# 04. Worker, adapter, workspace

## Worker (`aos worker --agent <id> [--once] [--poll 30]`)
Mỗi nhịp:
1. `recover`: task `running` có `lock_until` đã qua → lần chạy `lost`; task về `assigned` (còn lượt) hoặc `failed`.
2. `checkout` nguyên tử (`BEGIN IMMEDIATE`): task `assigned` của agent, ưu tiên thấp số trước, mọi phụ thuộc `done`; workspace `shared` thì dự án không có task khác đang chạy. Khoá 120 giây, `attempts + 1`, tạo dòng `runs`.
3. Chuẩn bị: workspace, bí mật của agent, môi trường tối thiểu + `env` của agent (điền `{project_slug}`, `{task_id}`), prompt (mẫu `prompt_file` + chuỗi ngữ cảnh).
4. Chạy adapter; mỗi 30 giây gia hạn khoá. Gia hạn thất bại (task bị huỷ/thu hồi) → dừng cả cây tiến trình. Quá `timeout_min` → dừng, kết quả `timeout`.
5. Áp hợp đồng đầu ra (nếu agent khai báo `handoff`), che bí mật trong nhật ký, `finish` → trạng thái mới.

Nhiều worker cho cùng agent hoặc khác agent chạy song song được; CSDL đảm bảo không trùng task.

## Adapter
| Adapter | Gọi gì | Thành công khi |
|---|---|---|
| `claude-code` | `claude -p --output-format json --permission-mode dontAsk --allowedTools … --disallowedTools … --max-turns N --model M --append-system-prompt …`, prompt qua stdin | Mã thoát 0, `is_error` false; dòng `AOS_RESULT: blocked/failed` trong `result` ghi đè |
| `shell` | Lệnh cố định trong cấu hình, prompt qua stdin | Mã thoát 0; `AOS_RESULT:` trong stdout ghi đè |

Ghi từ JSON của Claude Code (đã kiểm bằng lần chạy thật 2026-10-24, CLI 2.1.309): `session_id`, `num_turns`, `total_cost_usd` (ước tính phía máy, không phải hoá đơn), token từ `modelUsage` (gồm cả subagent; khoá `inputTokens`, `outputTokens`, `cacheReadInputTokens`, `cacheCreationInputTokens`), dự phòng `usage`; `permission_denials` lưu ra `permission_denials.json` và báo trong tóm tắt.

Tìm CLI: `claude.command` trong cấu hình (chuỗi hoặc danh sách) → `claude` trong PATH → `~/.local/bin/claude.exe` → bản đi kèm extension VS Code (mới nhất; tài liệu chính thức không cam kết đường dẫn này, nên cài bản native khi chạy lâu dài).

## Hợp đồng đầu ra (`[agents.<id>.handoff]`)
Agent ghi trạng thái cuối vào file (b3b4: `projects/<slug>/output/handoff.json`, khoá `status` = `done|blocked|failed`, `reason`). Worker chỉ tin file **ghi sau lúc bắt đầu chạy**; thiếu file mới khi adapter báo thành công → coi là `failed` (agent chưa báo xong).

## Workspace
- `shared`: chạy trong `workdir` của agent (b3b4 dùng chung thư mục, tách dự án bằng `WP_AGENT_PROJECT`). Khoá theo dự án ở bước checkout.
- `worktree`: `git worktree add data/worktrees/task-<id>` trên nhánh `aos/task-<id>`; làm lại thì dùng lại worktree; người duyệt xem diff của nhánh. Dọn worktree khi task `done` (Phase 3).

## Nhật ký mỗi lần chạy: `data/runs/run-<id>/`
`prompt.md`, `command.json`, `stdout.log`, `stderr.log`, `result.json`, `permission_denials.json` (nếu có). Đã che giá trị bí mật.
