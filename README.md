# TypePro workflows

Process data bằng interprocedural slicing, finetune model sinh type annotation
và chạy inference/evaluation. Code GPU và DeepSeek từ `SSH_Server` đã merge vào `main`.

## Kiến trúc

| Thư mục | Trách nhiệm |
| --- | --- |
| `typepro/data/` | prepare, preprocess, split, merge, verify |
| `typepro/training/` | generative QLoRA và contrastive ranker |
| `typepro/inference/` | model local, ranker và DeepSeek có resume |
| `typepro/publishing/` | publish shard và final Kaggle Dataset |
| `typepro/runtime.py` | log và audit mỗi lần chạy |
| `Python/` | AST, slicing, masking, project KB và evidence |
| `codet5p_type_retrieval/` | utilities, tests và entry point tương thích |
| `kaggle_notebooks/`, `ssh_notebooks/`, `vastai_notebooks/` | môi trường chạy |
| `reports/`, `docs/` | bằng chứng kiểm chứng và tài liệu hiện hành |

## Cài đặt

Python 3.10 trở lên. Chạy tại root repository:

```bash
python -m pip install -e . --no-deps
python -m pip install -r codet5p_type_retrieval/requirements-build.txt
python -m typepro --help
```

Finetune/infer GPU cần thêm `codet5p_type_retrieval/requirements.txt` và PyTorch
phù hợp CUDA. Xem [SSH](ssh_notebooks/README.md), [Vast.ai](vastai_notebooks/README.md).

## Process data

```bash
python -m typepro process-data --stage metadata --work-dir outputs/build
python -m typepro process-data --stage slice --work-dir outputs/build
python -m typepro process-data --stage finalize --work-dir outputs/build --output-dir outputs/dataset
python -m typepro verify --data-dir outputs/dataset
```

Đây là ví dụ tách stage. Build Dataset chính thức theo cấu hình 19 physical jobs,
revision lock và split ở [Kaggle runbook](kaggle_notebooks/README.md).

## Finetune và infer

```bash
accelerate launch --num_processes 1 -m typepro finetune \
  --data-dir datasets/typepro-python-generative-v19 \
  --output-dir outputs/qwen \
  --model-name Qwen/Qwen2.5-Coder-0.5B-Instruct

python -m typepro infer \
  --checkpoint outputs/qwen/best \
  --model-name Qwen/Qwen2.5-Coder-0.5B-Instruct \
  --input datasets/typepro-python-generative-v19/test.jsonl \
  --output outputs/qwen/test_predictions.jsonl

python -m typepro infer-api \
  --input datasets/typepro-python-generative-v19/test.jsonl \
  --output-dir outputs/deepseek
```

Dùng `COMMAND --help` để xem tham số. `finetune-ranker`/`infer-ranker` dành cho
contrastive model cũ. API inference đọc credential local/environment.
Script tmux hỗ trợ `TYPEPRO_REPO_DIR`, `TYPEPRO_DATA_DIR`, `TYPEPRO_OUTPUT_DIR`
và `TYPEPRO_VENV_DIR` cho train/infer local, không phụ thuộc username của host.

## Log, audit và kiểm tra

Mỗi lần chạy tạo `outputs/audit/<run>/run.json` và `console.log`: stage, revision,
thời gian, exit code, trạng thái và traceback. Đổi nơi lưu bằng `TYPEPRO_AUDIT_DIR`.
Lỗi dữ liệu xem thêm `project_status/*.json`, `export_summary` và manifest.
Chi tiết: [kiến trúc và audit](docs/architecture.md).

```bash
python -m pytest codet5p_type_retrieval/tests ssh_notebooks/test_infer_deepseek.py -q -p no:cacheprovider
```

Script cũ vẫn hoạt động qua entry point tương thích. Test CPU không thay cho
kiểm chứng train thật trên GPU. Hướng dẫn bài báo/TypeScript:
[upstream usage](docs/legacy_upstream.md).
