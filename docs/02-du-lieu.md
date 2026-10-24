---
status: draft
updated: 2026-10-24
---

# 02. Dữ liệu (SQLite, `data/aos.db`, chế độ WAL)

| Bảng | Cột chính | Ghi chú |
|---|---|---|
| `organizations` | `id`, `name`, `mission` | Một công ty; `mission` là mục tiêu cao nhất đưa vào ngữ cảnh |
| `agents` | `id` (slug), `org_id`, `name`, `role`, `reports_to`, `adapter`, `config_json`, `status` (`active`/`paused`) | Đồng bộ từ `config/agents.toml` (sơ đồ tổ chức). `config_json` không chứa bí mật |
| `goals` | `id`, `org_id`, `parent_id`, `title`, `description`, `status` | Mục tiêu / OKR, lồng nhau được |
| `projects` | `id`, `org_id`, `goal_id`, `slug`, `name`, `description` | Ví dụ `cong-nghe-doanh-nghiep-lop-3d`; `slug` truyền cho agent (b3b4: `WP_AGENT_PROJECT`) |
| `tasks` | `id`, `project_id`, `parent_id`, `title`, `description`, `agent_id`, `status`, `priority` (0 cao nhất), `attempts`, `max_attempts`, `lock_owner`, `lock_until`, `blocked_reason`, `result_summary`, `created_by`, `created_at`, `updated_at` | Khoá = `lock_owner` + `lock_until` (hết hạn thì worker khác thu hồi) |
| `task_deps` | `task_id`, `depends_on` | Task chỉ được checkout khi mọi task phụ thuộc đã `done` |
| `task_comments` | `id`, `task_id`, `author`, `kind` (`note`/`feedback`/`plan`/`agent`), `body`, `created_at` | Trao đổi theo luồng; góp ý khi trả lại task |
| `runs` | `id`, `task_id`, `agent_id`, `worker_id`, `status` (`running`/`succeeded`/`failed`/`blocked`/`timeout`/`lost`/`cancelled`), `started_at`, `ended_at`, `exit_code`, `session_id`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `cost_usd`, `num_turns`, `log_dir`, `error` | Một lần agent chạy một task |
| `audit_log` | `id`, `ts`, `actor` (`human:<tên>`/`agent:<id>`/`worker:<id>`/`system`), `action`, `entity`, `entity_id`, `data_json` | Chỉ thêm, không sửa, không xoá; không ghi bí mật |
| `schema_version` | `version` | Nâng cấp CSDL theo số phiên bản |

Phase 3 thêm: `approvals` (yêu cầu phê duyệt công cụ/chi phí), `budgets` (hạn mức theo công ty/dự án/agent).

## Quy tắc
- Thời gian lưu dạng ISO 8601 UTC.
- Mọi thay đổi trạng thái task trong cùng giao dịch với dòng `audit_log` tương ứng.
- Xoá cứng không có: task bị huỷ chuyển `cancelled`.
