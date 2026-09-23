# Train TypePro trên GPU SSH hiện tại

Notebook `01_typepro_qwen25_05b_a4000.ipynb` chạy toàn bộ quy trình verify,
fine-tune và inference bằng môi trường `.venv` của repository.

Cấu hình mặc định dành cho một RTX A4000 16 GB: QLoRA 4-bit NF4, FP16,
context 8192, label tối đa 64 token, micro-batch 2, gradient accumulation 8
và 3 epoch. Dataset Kaggle v15 đã tải nằm tại
`datasets/typepro-python-generative-v15` và phải vượt qua
`verify_dataset.py` trước khi train.

Để tải lại Dataset private vào thư mục mặc định của train/infer (streaming,
không buffer file lớn trong RAM):

```bash
.venv/bin/python ssh_notebooks/download_dataset.py \
  --output-dir datasets/typepro-python-generative-v15
```

Lệnh tải lấy version mới nhất tại thời điểm chạy; nếu Kaggle đã có version
khác v15, hãy tải vào thư mục version mới và cập nhật `DATA_DIR` tương ứng.

## Chạy training lâu dài bằng tmux

Dùng `tmux` để training tiếp tục chạy khi đóng notebook hoặc ngắt kết nối
SSH. Từ thư mục gốc của repository, tạo session chạy nền bằng launcher có
sẵn:

```bash
cd /home/anhnd_02/TypePro
tmux new-session -d -s typepro_train ./ssh_notebooks/run_training_tmux.sh
```

Launcher dùng cùng cấu hình training với notebook và nối cả stdout lẫn stderr
vào file:

```text
/home/anhnd_02/TypePro/outputs/qwen25-coder-05b-8192/train_tmux.log
```

Sau lần đo độ dài hoàn tất, kết quả được lưu tại
`outputs/qwen25-coder-05b-8192/train_lengths_cache.json`. Những lần chạy sau
sẽ nạp cache này thay vì tokenize lại toàn bộ tập train. Cache tự hết hiệu lực
khi dataset, model/tokenizer, giới hạn token, seed hoặc số lượng mẫu thay đổi.
Có thể buộc đo lại bằng tùy chọn `--no-length-cache` khi gọi
`train_generative.py` trực tiếp.

Vào session để theo dõi trực tiếp:

```bash
tmux attach -t typepro_train
```

Để rời session mà không dừng training, nhấn `Ctrl+B`, thả phím, rồi nhấn
`D`. Sau đó có thể đóng terminal hoặc ngắt SSH. Kết nối lại bằng lệnh
`tmux attach` ở trên.

Có thể xem log mà không cần attach:

```bash
tail -f /home/anhnd_02/TypePro/outputs/qwen25-coder-05b-8192/train_tmux.log
```

Kiểm tra session và GPU:

```bash
tmux has-session -t typepro_train && echo "training session is running"
nvidia-smi
```

Muốn dừng training an toàn, gửi `Ctrl+C` vào session rồi xem các dòng cuối
của log:

```bash
tmux send-keys -t typepro_train C-c
tail -n 50 /home/anhnd_02/TypePro/outputs/qwen25-coder-05b-8192/train_tmux.log
```

File log được mở ở chế độ append; mỗi lần chạy launcher sẽ thêm một dòng thời
gian bắt đầu và kết thúc để phân biệt các lần chạy.
Khi chạy qua `tmux`, progress bar động được tắt và training chỉ ghi metrics ở
update đầu tiên, sau đó mỗi 50 optimizer update và cuối mỗi epoch.

## Chạy inference lâu dài bằng tmux

Sau khi training hoàn tất và checkpoint `best` đã được tạo, chạy inference
trong một session nền riêng:

```bash
cd /home/anhnd_02/TypePro
tmux new-session -d -s typepro_infer ./ssh_notebooks/run_inference_tmux.sh
```

Launcher đọc tập test tại
`datasets/typepro-python-generative-v15/test.jsonl`, dùng checkpoint
`outputs/qwen25-coder-05b-8192/best` và ghi kết quả vào:

```text
/home/anhnd_02/TypePro/outputs/qwen25-coder-05b-8192/test_predictions.jsonl
```

Theo dõi session hoặc log inference:

```bash
tmux attach -t typepro_infer
tail -f /home/anhnd_02/TypePro/outputs/qwen25-coder-05b-8192/infer_tmux.log
```

Kiểm tra session, hoặc dừng inference bằng `Ctrl+C`:

```bash
tmux has-session -t typepro_infer && echo "inference session is running"
tmux send-keys -t typepro_infer C-c
```

Log inference cũng được mở ở chế độ append và có dòng thời gian bắt đầu, kết
thúc cùng exit code của mỗi lần chạy. Không chạy inference đồng thời với
training trên cùng GPU.

Nếu cần sửa notebook, hãy sửa `generate_notebook.py`, sau đó sinh lại bằng:

```bash
.venv/bin/python ssh_notebooks/generate_notebook.py
```

Tái sử dụng session đó:
```bash
tmux send-keys -t typepro_infer './ssh_notebooks/run_inference_tmux.sh' Enter
```

## DeepSeek API inference

Để chạy DeepSeek trên tập test v15 với checkpoint/resume và exact match,
xem [DEEPSEEK_INFERENCE.md](DEEPSEEK_INFERENCE.md).
