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

`typepro.training.contract_changing` (`return-contract-transport-v2`) giữ nguyên
mọi mẫu train gốc và thêm tối đa một synthetic cho mỗi parent đủ điều kiện.
**Giả định label gốc là hợp đồng return hợp lệ**, không yêu cầu suy luận lại
label từ code. Biến đổi mọi `return expr` thành `return [expr]` với label
`List[T]`, hoặc `return {"value": expr}` với label `Dict[str, T]`.
Đây là annotation chuyển từ hợp đồng gốc, không phải annotation duy nhất có
thể suy ra từ code; lỗi label gốc có thể truyền sang synthetic.

Direct caller và recursion được resolve theo lexical binding bằng LibCST.
Caller dùng `f(...)[0]` hoặc `f(...)["value"]` để tiếp tục nhận giá trị cũ.
Explicit `Class.method(...)` chỉ được sửa khi class binding khớp; receiver
instance/dynamic, alias và function reference thoát scope vẫn bị loại.
Không unwrap call của một binding bị shadow trong scope khác.

Các return trong nested helper không bị bọc. Bare return và implicit fallthrough
chỉ được hỗ trợ khi source contract chấp nhận None; bản synthetic thêm wrapper
cho đường None. Decorator, async/generator, special methods, fragment không
compile được và source không resolve được bị loại. Không chạy Dataset code.

Docstring target cũ được bỏ; literal và prose khác giữ nguyên. Candidate copy
có mask được đồng bộ sau khi kiểm tra chữ ký. Copy definition đã bỏ return
annotation, có sẵn trong JSONL,
chỉ được nhận khi qualified name khớp đúng file nguồn (từ ID export) và chữ ký
tham số khớp; không chỉ dựa vào tên class/function. Candidate ranking, identity
và nội dung ngoài các thay đổi được khai báo giữ nguyên. Evidence bundle chưa
được hỗ trợ bởi builder v24 này.

Builder chỉ đọc `train.jsonl`, `validation.jsonl`, `test.jsonl` và manifest của
dataset hiện tại. Các definition nằm sẵn trong `recommendation_types` được
sửa đồng bộ; không nạp project KB, tải thêm source hoặc chạy lại Kaggle shard.

Builder dùng hash(seed, parent ID) để chọn list/dict và chọn mẫu ổn định,
mặc định tối đa 5.000 synthetic, 100/project. Đo prompt bằng tokenizer Qwen thực,
gồm system/chat template; mẫu synthetic vượt 6.080 token bị loại. Không tăng
độ phủ bằng cách lặp lại cùng parent nhiều lần.

Sinh và kiểm tra dữ liệu, không train:

```bash
.venv/bin/python ssh_notebooks/run_type_changing.py --prepare-only
.venv/bin/python -m typepro.audit.contract_changing \
  --source datasets/typepro-python-generative-v24 \
  --data-dir datasets/typepro-python-generative-v24-contract-changing-c-s13
```

Audit độc lập so sánh AST để kiểm tra chỉ có wrapper, caller adapter và xóa
docstring đã khai báo; kiểm tra mọi mẫu gốc, hashes, eval bytes, ID và token budget.
Nó tạo `contract_transport_verification.json` cùng `review_samples.jsonl` để
review thủ công. Audit không chứng minh label gốc đúng hoặc whole-project
behavior. Trước train cần ít nhất 2.000 synthetic, 20 project, 20 source labels,
đúng tokenizer/budget và audit độc lập pass. Đây là gate độ phủ, không bảo đảm gain.

Chỉ khi quyết định train lại, commit code rồi chạy trong tmux:

```bash
tmux new-session -d -s typepro_train_v24_type_changing_c \
  '.venv/bin/python -u ssh_notebooks/run_type_changing.py'
```

Launcher mặc định chạy ngay; chỉ đợi nếu truyền `--wait-for-pid PID` hoặc
`--wait-for-idle-gpu`. Nó giữ snapshot từ Git commit để lần checkout sau không
thay source của job. Không dừng job khác. `--prepare-only` không tạo job train.
Nó dùng `launch_config.json` của `qwen25-coder-05b-v24-6k-2ep`, fresh base
adapter, QLoRA rank 16, 6144 token, 2 epoch, batch 1, accumulation 16,
LR 1e-4, seed 13, FP16, SDPA và length grouping/cache theo launcher baseline.
Giữ nguyên hyperparameters/epochs; thêm mẫu làm tăng số bước và token so với
baseline. Đây chưa phải so sánh công bằng ngân sách với cấu hình B.

Dataset mặc định: `datasets/typepro-python-generative-v24-contract-changing-c-s13`.
Validation/test được copy nguyên byte; chỉ train có synthetic. Audit chứa
source/output hashes, counts, skip reasons và hash code; `synthetic_pairs.jsonl`
ghi liên kết parent. Không cần tạo lại shard Kaggle.

Builder cũ `typepro.training.type_changing` (`type-changing-v1`) vẫn giữ để
tái lập pilot 133 mẫu đã hủy. Launcher không cho train lại pilot thiếu độ phủ.

Output: `outputs/qwen25-coder-05b-v24-6k-2ep-type-changing-c`. Xem
`launch_config.json`, `run_status.json` và `train_tmux.log`. Sau train, checkpoint
`best` tự infer test bằng greedy. Trạng thái `waiting` chưa phải đang train;
chỉ `complete` và prediction/metric thực tế mới chứng minh run đã hoàn tất.
