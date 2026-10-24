Đọc AGENTS.md. Chạy dự án "{project_slug}" (biến WP_AGENT_PROJECT={project_slug} đã đặt sẵn) ở chế độ PIPELINE nhưng **CHỈ LÀM BƯỚC 1 VÀ BƯỚC 2** rồi dừng: không dựng site, không chạy Docker, không làm bước 3–6. Đầu vào ở projects/{project_slug}/inputs/, đầu ra ở projects/{project_slug}/output/. Không hỏi qua chat: câu hỏi chặn ghi vào 16-risks-open-questions.md kèm đề xuất mặc định. Kết thúc khi `step_gate.py 2` đạt (hoặc ghi rõ vì sao chưa đạt).

{context}

Dòng cuối cùng của câu trả lời: `AOS_RESULT: done|blocked|failed - <tóm tắt một câu>`.
