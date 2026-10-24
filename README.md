# agentic-os

Bộ điều phối ("công ty") cho các agent ("nhân viên") của pipeline làm website B1–B6. Giao việc theo task, mỗi task một agent tại một thời điểm, lưu nhật ký + token + chi phí, người duyệt trước khi chốt. Độc lập với code của agent: gọi agent qua CLI, đọc kết quả qua hợp đồng đầu ra.

Thiết kế: `docs/` (bắt đầu từ `00-tong-quan.md`). Trạng thái: Phase 1–3 xong (`docs/06-lo-trinh.md`).

## Cài đặt
- Python 3.11+ (chỉ thư viện chuẩn), git, Claude Code CLI (tự tìm; khuyên cài bản native).
- `copy config\agents.example.toml config\agents.toml` rồi sửa `workdir` từng agent.
- Bí mật (nếu cần): `config\secrets\<agent>.env` dạng `TEN=giá trị`, khai tên trong `secrets = [...]`.

## Dùng
```
python -m aos init                                   # tạo CSDL, nạp tổ chức + agent
python -m aos goal "Giao 2 site/tháng"
python -m aos project cong-nghe-doanh-nghiep-lop-3d "LỚP xưởng in 3D" --goal 1
python -m aos add cong-nghe-doanh-nghiep-lop-3d "Làm site đủ 6 bước" --agent b3b4
python -m aos worker --agent b3b4                    # chạy liên tục (thêm --once: một nhịp)
python -m aos list | show <id> | status
python -m aos review <id> --approve                  # hoặc --reject "góp ý cho agent"
python -m aos reopen <id> --note "đã tạo site trong Local"   # task bị chặn / thất bại → giao lại
```
Ngân sách và phê duyệt (Phase 3, `docs/07-ngan-sach-phe-duyet.md`):
```
python -m aos budget set --scope agent --id b3b4 --usd 20 --period month
python -m aos budget set --scope task --id 12 --usd 3
python -m aos budget list
python -m aos approvals                              # yêu cầu chờ duyệt (hết ngân sách, agent xin quyền)
python -m aos approve <id> --raise-usd 2             # hoặc: python -m aos deny <id> --note "..."
python -m aos agent resume b3b4                      # bật lại agent tự dừng vì hết ngân sách
```
Nhật ký từng lần chạy: `data/runs/run-<id>/`. CSDL: `data/aos.db`.

## Test
`python -m unittest discover tests` (không gọi mô hình thật; dùng agent giả).
