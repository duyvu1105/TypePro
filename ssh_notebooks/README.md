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

Nhấn `Ctrl-b`, `d` để detach. Launcher tự infer toàn bộ test split sau khi
fine-tune thành công, dùng checkpoint `best` và ghi `test_predictions.jsonl`.
Inference dùng greedy (`do_sample=False`, `num_beams=1`) tường minh, kể cả
khi generation config của base model bật sampling. Quy tắc này áp dụng cho
cả infer tự động sau train và launcher infer riêng.
Xem log train và infer trong `train_tmux.log`. Đặt
`TYPEPRO_INFERENCE_BATCH_SIZE` để đổi batch infer (mặc định 1).
Để chạy lại infer riêng với checkpoint đã có:

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
Cell fine-tune tự chạy infer; cell infer riêng có `RERUN_INFERENCE = False`
để tránh chạy hai lần khi Run All. Đổi thành `True` để infer lại độc lập.
Mỗi lần gọi stage lưu `outputs/audit/<run>/run.json` và `console.log`; log tmux
giữ thêm output native/subprocess. Training giữ checkpoint, cấu hình và length
cache trong output. Không commit checkpoint, Dataset hoặc credential.

## Type-changing augmentation, cấu hình C

`typepro.training.type_changing` đọc train v24 đã export, giữ nguyên mọi mẫu
gốc và thêm tối đa một mẫu synthetic cho mỗi parent đủ điều kiện. Chỉ biến đổi
return target: bọc kết quả bằng list/dict, đổi string-list literal thành
float-list literal, hoặc constructor class đơn giản thành tham chiếu class.
Các phép biến đổi là chương trình tổng hợp mới; không phải refactor tương đương.

Type ban đầu phải khớp bộ suy luận tĩnh giới hạn (literal, builtin không bị
shadow, tham số scalar có annotation, một số phép toán và class đơn giản).
Chỉ xét hàm có return cuối tường minh và các return có cùng type. Bỏ qua
decorator/async/generator, scope phức tạp, caller/reference cần sửa, candidate
copy không xác minh được và evidence bundle chưa hỗ trợ. Docstring target được
bỏ khỏi bản synthetic để không giữ mô tả return cũ. Các bản copy candidate
khớp AST được sửa đồng bộ; ranking và candidate identities giữ nguyên.
Không chạy source code của Dataset. Nhãn tổng hợp theo chính sách annotation
cụ thể, không khẳng định đó là annotation duy nhất tác giả có thể chọn.

Sinh và kiểm tra dữ liệu, không train:

```bash
.venv/bin/python ssh_notebooks/run_type_changing.py --prepare-only
```

Sau khi commit code, chạy trong tmux (bỏ `--wait-for-pid` nếu không có job trước):

```bash
tmux new-session -d -s typepro_train_v24_type_changing_c \
  '.venv/bin/python -u ssh_notebooks/run_type_changing.py --wait-for-pid PREDECESSOR_PID'
```

Launcher đợi đúng process trước đó và GPU 0 rảnh, giữ snapshot từ Git commit
để lần checkout sau không thay source của job đang đợi. Không dừng job khác.
Nó dùng `launch_config.json` của `qwen25-coder-05b-v24-6k-2ep`, fresh base
adapter, QLoRA rank 16, 6144 token, 2 epoch, batch 1, accumulation 16,
LR 1e-4, seed 13, FP16, SDPA và length grouping/cache theo launcher baseline.
Giữ nguyên hyperparameters/epochs; thêm mẫu làm tăng số bước và token so với
baseline. Đây chưa phải so sánh công bằng ngân sách với cấu hình B.

Dataset mặc định: `datasets/typepro-python-generative-v24-type-changing-c-s13`.
Validation/test được copy nguyên byte; chỉ train có synthetic. Audit chứa
source/output hashes, counts, skip reasons và hash code; `synthetic_pairs.jsonl`
ghi liên kết parent. Không cần tạo lại shard Kaggle.

Output: `outputs/qwen25-coder-05b-v24-6k-2ep-type-changing-c`. Xem
`launch_config.json`, `run_status.json` và `train_tmux.log`. Sau train, checkpoint
`best` tự infer test bằng greedy. Trạng thái `waiting` chưa phải đang train;
chỉ `complete` và prediction/metric thực tế mới chứng minh run đã hoàn tất.
