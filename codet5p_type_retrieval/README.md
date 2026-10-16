# Utilities, tests và entry points tương thích

Logic chính đã chuyển vào `typepro/`; script tại đây chuyển tiếp cùng arguments:

| Script cũ | Implementation | CLI |
| --- | --- | --- |
| `prepare_dataset.py` | `typepro/data/prepare.py` | `process-data` |
| `preprocess_generative.py` | `typepro/data/preprocess.py` | `preprocess` |
| `merge_shards.py`, `verify_dataset.py` | `typepro/data/` | `merge`, `verify` |
| `train_generative.py`, `train.py` | `typepro/training/` | `finetune`, `finetune-ranker` |
| `infer_generative.py`, `infer.py` | `typepro/inference/` | `infer`, `infer-ranker` |
| `publish_kaggle.py`, `publish_shard.py` | `typepro/publishing/` | `publish`, `publish-shard` |

Chạy `python -m typepro COMMAND --help` tại root. Không duy trì hai bản logic.
Các utilities, chat formatting, type labels, sampler và evidence checkers
vẫn dùng chung tại đây.

Xem [README](../README.md), [kiến trúc](../docs/architecture.md),
[Kaggle](../kaggle_notebooks/README.md) và [GPU SSH](../ssh_notebooks/README.md).
