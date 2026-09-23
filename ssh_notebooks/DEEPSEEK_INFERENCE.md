# DeepSeek inference trên TypePro test v15

Script `infer_deepseek.py` gửi trường `input` của từng mẫu trong
`datasets/typepro-python-generative-v15/test.jsonl` tới DeepSeek Flash để dự
đoán annotation. Ground-truth `label` **không** được gửi trong prompt. Script
chuẩn hóa prediction bằng cùng `normalize_type_label()` với pipeline Qwen rồi
tính exact match. Đây là API inference, không phải fine-tune.

Model mặc định là `deepseek-flash`, dùng Chat Completions ở non-thinking mode
và tối đa 128 output tokens. Xem [DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)
và [Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)
để kiểm tra model, chi phí và tham số trước khi chạy. Chạy toàn bộ tập test
gửi **3.277 request** cùng code context tới dịch vụ DeepSeek và có thể phát
sinh phí theo token.

## Chuẩn bị

Đặt `DEEPSEEK_API_KEY=...` trong `.env` ở root repository hoặc export biến
môi trường cùng tên. `.env` phải có quyền `600` và đã được `.gitignore`; script
chỉ đọc key để xác thực, không in key vào log hay kết quả. Dữ liệu test v15 phải
đã tải và đi qua `verify_dataset.py`.

Có thể chạy thử đúng một mẫu trước khi chạy toàn bộ:

```bash
cd /home/anhnd_02/TypePro
.venv/bin/python ssh_notebooks/infer_deepseek.py --max-new 1
```

Mẫu thử được lưu trong cùng checkpoint và sẽ tự được bỏ qua ở lần chạy sau.

## Chạy lâu dài bằng tmux

```bash
cd /home/anhnd_02/TypePro
tmux new-session -d -s typepro_deepseek_v15 ./ssh_notebooks/run_deepseek_tmux.sh
tail -f outputs/deepseek-flash-v15/infer_tmux.log
```

Xem session trực tiếp bằng `tmux attach -t typepro_deepseek_v15`; để rời mà
không dừng job, nhấn `Ctrl+B`, rồi `D`. Kiểm tra session:

```bash
tmux has-session -t typepro_deepseek_v15 && echo "DeepSeek inference đang chạy"
```

Nếu cần dừng, dùng `tmux send-keys -t typepro_deepseek_v15 C-c`. Để tiếp tục,
chạy lại đúng lệnh `tmux new-session` ở trên sau khi session cũ đã kết thúc.
Nếu báo `duplicate session`, hãy attach vào session đang có; không khởi chạy
job thứ hai cùng output directory. Script cũng dùng file lock để chặn hai
tiến trình cùng ghi một checkpoint.

## Checkpoint và exact match

- `outputs/deepseek-flash-v15/checkpoint.sqlite3`: lưu từng prediction bằng
  transaction; resume bỏ qua ID đã lưu. Không xóa file này nếu muốn tiếp tục.
- `outputs/deepseek-flash-v15/test_predictions.jsonl`: xuất các prediction đã
  hoàn tất theo thứ tự test.
- `outputs/deepseek-flash-v15/summary.json`: số mẫu đúng, tỷ lệ exact match,
  số mẫu còn lại và tổng token API báo về.
- `outputs/deepseek-flash-v15/infer_tmux.log`: tiến độ và lỗi (không chứa key).

Sau khi bị dừng, có thể xuất lại kết quả và tính điểm phần đã xong **không
gọi API**:

```bash
.venv/bin/python ssh_notebooks/infer_deepseek.py --score-only
```

Trong `summary.json`, `exact_match_accuracy_completed` chỉ tính trên các mẫu
đã hoàn tất; `exact_match_accuracy_full_test` chỉ có giá trị khi `status` là
`complete` và đủ 3.277 mẫu. Khi đổi Dataset, model hoặc tham số request, hãy
dùng `--output-dir` mới: script từ chối trộn kết quả khác cấu hình vào cùng
checkpoint. Lỗi API hoặc response không hoàn chỉnh sẽ dừng job nhưng giữ các
prediction đã checkpoint để chạy tiếp.
