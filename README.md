# TypePro: process data → finetune → inference

Luồng chính: build 21 partition trên Kaggle → merge và publish Dataset → tải về
server GPU → finetune Qwen bằng QLoRA → infer trên tập test. Các lệnh dưới đây
chạy theo thứ tự; phần giải thích và điều kiện chuyển bước nằm phía sau.

## Chạy shard thường ngày

Sau khi đã cài môi trường và đặt ba credential, chỉ cần:

```powershell
# Chuẩn bị và xem trước 21 job; tự chọn code mới nhất trên GitHub cho lần đầu.
python kaggle_notebooks/schedule_shards.py

# Submit kế hoạch đã chuẩn bị, tối đa 5 job đang chạy/account.
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/schedule_shards.py --push --watch
```

Không phải tự lấy SHA, tạo biến hay commit mỗi lần chạy. Ledger mặc định là
`typepro_kernel_versions/latest_run.json`. Chạy lại hai lệnh trên sẽ tiếp tục
kế hoạch đã lưu. Để bắt đầu một đợt mới và lấy code mới nhất tại thời điểm đó:

```powershell
python kaggle_notebooks/schedule_shards.py --new-run
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/schedule_shards.py --push --watch
```

`--new-run` lưu bản sao ledger cũ trước khi chuẩn bị đợt mới. Code mới nhất ở đây
là code **đã có trên GitHub**, không bao gồm sửa đổi chưa push từ máy local.
Sau khi shard hoàn tất, tiếp tục bước kiểm tra và merge bên dưới.

## Các lệnh theo thứ tự

### A. Máy local — PowerShell, tại root repository

```powershell
# 1. Cài môi trường điều phối và kiểm tra CLI.
python -m pip install -e . --no-deps
python -m pip install -r requirements/build.txt pytest uv
python -m typepro --help

# 2. Sinh notebook theo kế hoạch hiện tại: 21 job, 3 account.
python kaggle_notebooks/generate_notebooks.py --shards 10 --runner-accounts duyvu1105 duymign vdduy1105 --dataset-owner duyvu1105

# 3. Chạy kiểm thử và render thử; phải thành công trước khi push.
python -m pytest tests ssh_notebooks/test_infer_deepseek.py -q -p no:cacheprovider
python kaggle_notebooks/commit_shard_versions.py

# 4–6. Dry-run: tự chọn revision và ledger; kiểm tra đủ 21 job.
# Thêm --new-run nếu chủ động bắt đầu một đợt mới, thay vì tiếp tục đợt cũ.
python kaggle_notebooks/schedule_shards.py

# 7. Submit các shard, tối đa 5 job đang chạy trên mỗi account.
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/schedule_shards.py --push --watch

# 8. CHỜ các version vừa submit chạy xong và publish shard Dataset.
# Chạy lại các lệnh kiểm tra dưới đây khi cần; chưa merge nếu còn lỗi/đang chạy.
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_shard_versions.py --check-status
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_merge_finalize.py --check-inputs

# 9. Khi 21 shard đã sẵn sàng: dry-run merge rồi mới push.
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_merge_finalize.py
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_merge_finalize.py --push

# 10. CHỜ merge/publish hoàn tất; chạy lại để xem trạng thái.
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_merge_finalize.py --check-status
```

### B. Server GPU — Bash trên Linux/SSH hoặc terminal Vast.ai

```bash
# 11. Clone repository nếu máy chưa có; SHA đã chọn có trong output scheduler.
git clone --branch main https://github.com/duyvu1105/TypePro.git
cd TypePro
export REVISION="THAY_BANG_SHA_TRONG_OUTPUT_SCHEDULER"
git fetch origin main
git checkout --detach "$REVISION"

# 12. Mở phiên tmux; chạy các lệnh còn lại bên trong phiên này.
tmux new -s typepro_gpu

# 13. Dùng PyTorch/CUDA đã có trên host và cài dependencies.
python -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -e . --no-deps
python -m pip install -r requirements/build.txt -r requirements/training.txt requests
nvidia-smi
python -c 'import torch; print(torch.__version__, torch.version.cuda); assert torch.cuda.is_available(), "CUDA unavailable"'

# 14. Đặt credential có quyền đọc Dataset private vào kaggle.json trước bước này.
chmod 600 kaggle.json
export TYPEPRO_DATA_DIR="$PWD/datasets/typepro-python-generative"
export TYPEPRO_OUTPUT_DIR="$PWD/outputs/qwen25-coder-05b"
mkdir -p "$TYPEPRO_OUTPUT_DIR"
python ssh_notebooks/download_dataset.py --credential kaggle.json --output-dir "$TYPEPRO_DATA_DIR"

# 15. Kiểm tra Dataset tải về; chỉ train khi verified=true.
python -m typepro verify --data-dir "$TYPEPRO_DATA_DIR"
python -c 'import json,os,pathlib; p=pathlib.Path(os.environ["TYPEPRO_DATA_DIR"]); m=json.loads((p/"manifest.json").read_text()); print(json.dumps({"source":m.get("source"),"output":m.get("output")}, indent=2))'

# 16. Finetune toàn bộ train split trên 1 GPU, tự infer khi thành công.
export CUDA_VISIBLE_DEVICES=0
export TOKENIZERS_PARALLELISM=false
accelerate launch --num_machines 1 --num_processes 1 --mixed_precision fp16 -m typepro finetune \
  --data-dir "$TYPEPRO_DATA_DIR" \
  --output-dir "$TYPEPRO_OUTPUT_DIR" \
  --model-name Qwen/Qwen2.5-Coder-0.5B-Instruct \
  --input-length 8192 \
  --label-length 64 \
  --batch-size 1 \
  --gradient-accumulation-steps 16 \
  --epochs 3 \
  --learning-rate 1e-4 \
  --mixed-precision fp16 \
  --attn-implementation sdpa \
  --gradient-checkpointing \
  --group-by-length \
  --length-cache \
  --preview-samples 0 \
  --seed 13 \
  --log-every 50

# 17. Khi train kết thúc thành công, kiểm tra checkpoint tốt nhất.
test -f "$TYPEPRO_OUTPUT_DIR/best/adapter_config.json"

# 18. Tùy chọn: chạy lại infer riêng bằng checkpoint đó.
python -m typepro infer \
  --checkpoint "$TYPEPRO_OUTPUT_DIR/best" \
  --model-name Qwen/Qwen2.5-Coder-0.5B-Instruct \
  --input "$TYPEPRO_DATA_DIR/test.jsonl" \
  --output "$TYPEPRO_OUTPUT_DIR/test_predictions.jsonl" \
  --input-length 8192 \
  --label-length 64 \
  --batch-size 1

# 19. Kiểm tra số prediction và số dòng test tương ứng.
wc -l "$TYPEPRO_DATA_DIR/test.jsonl" "$TYPEPRO_OUTPUT_DIR/test_predictions.jsonl"
```

## Giải thích các bước

**Bước 1–3 — Chuẩn bị môi trường và notebook.** Chạy trên nhánh `main` tại root
repository. Cần Git, Python từ 3.10 và ba credential local: `kaggle.json` cho
`duyvu1105`, `kaggle2.json` cho `duymign`, `kaggle3.json` cho `vdduy1105`.
Các file này được ignore; không đưa nội dung key vào lệnh hoặc log. Script tự
kiểm tra username khi xác thực.

Notebook phải sinh từ generator. Kiểm thử thất bại thì dừng trước bước push.
Nếu vừa sửa code/generator và muốn Kaggle dùng các sửa đổi đó, cần kiểm tra,
commit và push chúng trước bước 4. Nếu chỉ chạy lại code đã có trên GitHub,
không cần commit hoặc Git push lần nữa. Môi trường local nên dùng cùng phiên bản
code đã chọn để generator, scheduler và code chạy trên Kaggle đồng bộ.

**Bước 4–6 — Tự chọn code và lưu kế hoạch chạy.** `revision` là SHA 40 ký tự
nhận diện một commit Git, tức một phiên bản code. Nó không phải version Dataset
hay version kernel Kaggle. Nếu chưa có ledger, scheduler tự hỏi GitHub lấy commit
mới nhất của `origin/main`, rồi lưu SHA và kế hoạch ngay trong bước dry-run.
Không sửa checkout local và không tự commit/push Git.

Khi đã có ledger, lệnh mặc định giữ SHA đã lưu, kể cả khi GitHub có commit mới,
để các shard trong một đợt dùng cùng code. `--new-run` bắt đầu đợt mới và chọn
lại code mới nhất. Các tùy chọn `--revision <SHA>` và `--state <file>` vẫn dùng
được nếu cần tự chỉ định; không bắt buộc cho luồng thông thường.

Một revision có thể chạy nhiều lần mà không tạo commit mới. Đợt mới tạo version
kernel Kaggle mới khi submit; Git revision không cần thay đổi.

Ledger mới cho phép submit lại jobs; dữ liệu tương thích vẫn có thể được resume
theo chính sách cache của notebook. Nó không tự buộc rebuild toàn bộ raw slices.
Git push cập nhật code trên GitHub; Kaggle `--push` tạo version kernel và submit job.

**Bước 6–7 — Process data trên Kaggle.** Scheduler pin code bằng SHA 40 ký tự,
đọc `shard_account_plan.json` và điều phối 21 partition:

| Account | Số job | Shard Dataset |
| --- | ---: | --- |
| `duyvu1105` | 7 | private |
| `duymign` | 7 | public |
| `vdduy1105` | 7 | public |

Mỗi job chuẩn bị metadata, checkout project theo `configs/project_revision_lock.json`,
build một KB cho mỗi project, export slice/candidates với target đã mask, audit
và publish shard. Các physical coordinate lấy nguyên từ plan, gồm các partition
`/20`, `/30`, `/40`, `/90`; không tự chia lại thành 21 shard bằng nhau.

`--watch` đợi slot trống để submit phần còn lại, tối đa 5 job/account. Nó kết thúc
khi đã submit đủ, **không đợi tất cả Dataset hoàn tất**. Giữ cùng SHA và ledger
khi tiếp tục lần chạy bị gián đoạn; chạy lại bước 7 để scheduler dùng trạng thái
đã lưu. Một đợt độc lập dùng `--new-run` ở bước dry-run.
Nếu ledger còn trạng thái `submitting`, kiểm tra version remote trước khi retry.

Nếu chỉ muốn chạy 15 job đầu như các đợt trước: thêm `--jobs-per-account 5` vào
cả dry-run và push, dùng ledger riêng. Sau khi muốn chạy nốt 4 job, dùng
`--skip-jobs-per-account 5` với một ledger khác; vẫn dry-run trước khi push.
Không chạy đồng thời luồng đầy đủ và luồng chia đợt cho cùng một lần rebuild.

**Bước 8 — Xác nhận shard sẵn sàng.** Kiểm tra đúng version vừa submit, không
chỉ nhìn trạng thái thành công của version cũ. `--check-inputs` chỉ kiểm tra khả
năng liệt kê Dataset; Dataset cũ còn tồn tại không chứng minh bản mới đã publish.
Xem log/output của version tương ứng: `shard_manifest.json` phải đúng coordinate,
không có project bị thiếu ngoài chính sách cho phép; runtime schema phải khớp
code hiện tại. Payload cần có `metadata`, `raw_slices`, `project_status`,
`project_kb` và các manifest. Shard lỗi thì sửa/retry đúng partition, chưa merge.

**Bước 9–10 — Merge và publish final Dataset.** Chạy dưới `duyvu1105`, lấy đúng
21 inputs từ `shard_merge_plan.json`. Notebook kiểm tra manifest/schema, merge,
preprocess thành `train.jsonl`, `validation.jsonl`, `test.jsonl`, kiểm tra output
và publish private Dataset `duyvu1105/typepro-python-generative`.
`configs/test_projects.txt` là danh sách ưu tiên; `test_projects.txt` và
`test_split_audit.json` trong Dataset ghi tập test thực tế đã chọn.

Chờ kernel `duyvu1105/merge-dataset` hoàn tất và log xác nhận publish đúng version
mới. Nếu chỉ publish bị lỗi sau merge, dùng recovery trong
[Kaggle runbook](kaggle_notebooks/README.md). Giữ code `main` tại revision đã
kiểm tra trong suốt đợt chạy để merge dùng cùng implementation với shards.

**Bước 11–13 — Chuẩn bị GPU.** Chạy trên server Linux có NVIDIA GPU và PyTorch
phù hợp CUDA, có thể là máy SSH hoặc Vast.ai. Nếu repository đã tồn tại, bỏ lệnh
clone và `cd` vào repository đó. Thay placeholder `REVISION` bằng SHA trong
output scheduler hoặc trường `revision` của ledger đã lưu.
`--system-site-packages` cho phép venv dùng PyTorch/CUDA đã cài trên host; nếu
kiểm tra CUDA thất bại, sửa môi trường trước khi train.

`tmux new` mở một shell tương tác mới: nhập các lệnh từ bước 13 trong shell đó.
Nhấn `Ctrl-b`, rồi `d` để detach; quay lại bằng `tmux attach -t typepro_gpu`.
Nếu chỉ muốn dùng notebook, xem [Vast.ai](vastai_notebooks/README.md) hoặc
[SSH](ssh_notebooks/README.md); đó là cách chạy thay thế cho phần B.

**Bước 14–15 — Tải và xác minh dữ liệu.** Đặt credential được cấp quyền đọc
Dataset private vào file `kaggle.json` trên server, không in nội dung file.
Downloader stream các split và metadata phục vụ train; không tải toàn bộ project
KB. Vì vậy `verify` có thể báo bỏ qua đối chiếu KB khi thư mục này không có.
Nó vẫn kiểm tra các split tải về theo manifest, gồm hash và ràng buộc dữ liệu.

Downloader lấy bản mới nhất tại thời điểm tải, không pin version theo tên thư mục.
Đối chiếu `manifest.source`, số mẫu trong `manifest.output` và audit tập test với
version vừa publish trước khi train; lưu manifest cùng kết quả thí nghiệm. Chạy
lại download nếu Dataset bị cập nhật giữa quá trình tải và verify báo sai hash.
`verified=true` không có nghĩa số mẫu tự động bằng v18; phải đối chiếu số mẫu/ID
nếu mục tiêu là giữ nguyên benchmark cũ.

**Bước 16–17 — Finetune.** Ví dụ dùng Qwen2.5-Coder-0.5B-Instruct, QLoRA NF4
4-bit, FP16, context 8192, batch 1, accumulation 16 và 3 epoch. Không có
`--train-samples` nghĩa là dùng toàn bộ train split. Để chạy thử nhanh, thêm
`--train-samples 7000` nếu tập train có ít nhất 7000 dòng; validation vẫn đầy đủ.
Nếu thiếu VRAM, giảm context xuống 4096 và dùng cùng cấu hình khi infer.

Fine-tune tự infer toàn bộ `test.jsonl` sau khi train thành công, dùng checkpoint
`best`, cùng model/context/label length và ghi `OUTPUT_DIR/test_predictions.jsonl`.
Batch infer mặc định 1; đổi bằng `--inference-batch-size N`, đổi đường dẫn bằng
`--inference-output PATH`. Dùng `--no-infer-after-training` nếu chỉ muốn train.
Lệnh `python -m typepro infer` vẫn chạy độc lập. Trong notebook, bật
`RERUN_INFERENCE` ở cell infer riêng khi cần chạy lại.

Checkpoint `best` gồm LoRA adapter và tokenizer, được cập nhật khi validation
loss tốt hơn. Bước kiểm tra file không thay cho kiểm tra tiến trình train đã kết
thúc thành công; checkpoint từ epoch trước vẫn có thể còn khi epoch sau bị lỗi.
Dùng output directory riêng cho mỗi thí nghiệm để tránh nhầm checkpoint cũ.

**Bước 18–19 — Inference và đánh giá.** Giữ cùng base model, context length và
label length với train. Input là các dòng JSONL đã preprocess, gồm prompt `input`
và nhãn `label`; đây là infer/evaluate trên tập test, không nhận trực tiếp một
file Python bất kỳ. Mỗi dòng prediction có `id`, prediction, nhãn chuẩn hóa và
`exact_match`. Console in số mẫu, số dự đoán đúng và `exact_match_accuracy`.
Hai số dòng ở bước 19 phải bằng nhau sau một lượt inference thành công.

## Mã nguồn và log

| Vị trí | Trách nhiệm |
| --- | --- |
| `typepro/analysis/` | AST, slicing, masking, project KB và retrieval |
| `typepro/data/` | Prepare, preprocess, split, merge và verify |
| `typepro/training/` | Generative QLoRA |
| `typepro/inference/` | Generative model và DeepSeek API |
| `typepro/publishing/` | Đóng gói/publish shard và final Dataset |
| `typepro/shared/` | Dữ liệu, nhãn kiểu và định dạng chat dùng chung |
| `typepro/audit/` | Kiểm tra bằng chứng và context |
| `tests/`, `configs/`, `requirements/` | Kiểm thử, cấu hình và dependencies |
| Các thư mục `*_notebooks/` | Generator, notebook và launcher theo môi trường |

Giải thích process data từ đầu đến cuối: [docs/data_pipeline.md](docs/data_pipeline.md).

CLI `python -m typepro ...` ghi `outputs/audit/<run>/run.json` và `console.log`;
đổi nơi lưu bằng `TYPEPRO_AUDIT_DIR`. Training qua `accelerate -m typepro` cũng
đi qua CLI này. Trên Kaggle, xem thêm log kernel, `project_status/*.json`,
`export_summary`, `context_audit.json`, runtime/shard/final manifests.
Chi tiết tại [kiến trúc và audit](docs/architecture.md).

Các kiểm tra bằng chứng có thể chạy lại bằng `python -m typepro.audit.regressions`
hoặc `python -m typepro.audit.inventory`, kèm `--output <duong-dan-json>`.
Không đưa Dataset, checkpoint, credential hay output tạm vào Git.
