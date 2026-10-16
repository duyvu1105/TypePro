# Chạy GPU qua SSH

Logic finetune ở `typepro/training/`; inference ở `typepro/inference/`.
Thư mục này chứa launcher tmux, downloader và notebook generator.
Xem [kiến trúc](../docs/architecture.md) và [CLI chung](../README.md).

## Chuẩn bị

Tại root repository trên server Linux có GPU NVIDIA/CUDA:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e . --no-deps
python -m pip install -r requirements/training.txt requests
```

Cài PyTorch phù hợp CUDA của host. Credential Kaggle chỉ dùng khi download,
không đặt trong notebook hay Git. Downloader hỗ trợ streaming để tránh giữ
Dataset lớn trong RAM:

```bash
python ssh_notebooks/download_dataset.py --output-dir datasets/typepro-python-generative-v19
python -m typepro verify --data-dir datasets/typepro-python-generative-v19
```

Downloader lấy bản mới nhất tại thời điểm chạy: kiểm tra manifest thay vì suy
ra version từ tên thư mục. Muốn dùng bản khác, đặt `TYPEPRO_DATA_DIR` tương ứng.

## Train, infer qua tmux

```bash
export TYPEPRO_DATA_DIR="$PWD/datasets/typepro-python-generative-v19"
export TYPEPRO_OUTPUT_DIR="$PWD/outputs/qwen25-coder-05b"
tmux new-session -d -s typepro_train ./ssh_notebooks/run_training_tmux.sh
tmux attach -t typepro_train
```

Nhấn `Ctrl-b`, `d` để detach. Xem `train_tmux.log` trong output directory.
Sau khi checkpoint `best` tồn tại:

```bash
tmux new-session -d -s typepro_infer ./ssh_notebooks/run_inference_tmux.sh
```

Launcher tự tìm repository; override bằng `TYPEPRO_REPO_DIR` và môi trường bằng
`TYPEPRO_VENV_DIR`. Preset train: Qwen2.5-Coder-0.5B, QLoRA NF4, FP16, 8192 token,
batch 1, accumulation 16, 3 epoch. Notebook có cấu hình riêng ở cell đầu;
chỉnh hyperparameters theo GPU, không coi preset là bằng chứng đã test trên host.

DeepSeek có resume SQLite và khóa chống hai tiến trình ghi cùng output:

```bash
python -m typepro infer-api --input "$TYPEPRO_DATA_DIR/test.jsonl" --output-dir outputs/deepseek --max-new 1
```

Lệnh này gửi dữ liệu đến API và có thể phát sinh phí. Đặt `DEEPSEEK_API_KEY`
qua environment hoặc `.env` có quyền `600` trên Linux. Xem
[hướng dẫn API](DEEPSEEK_INFERENCE.md).

## Notebook và audit

`01_typepro_qwen25_05b_a4000.ipynb` được sinh từ `generate_notebook.py`:

```bash
python ssh_notebooks/generate_notebook.py
```

Notebook đọc `TYPEPRO_REPO_DIR` (mặc định `~/TypePro`) và `TYPEPRO_DATA_DIR`.
Mỗi lần gọi stage lưu `outputs/audit/<run>/run.json` và `console.log`; log tmux
giữ thêm output native/subprocess. Training giữ checkpoint, cấu hình và length
cache trong output. Không commit checkpoint, Dataset hoặc credential.
