# TypePro Kaggle notebooks

This folder contains upload-ready notebooks for the Python parameter-only dataset:

- `01_typepro_shard_00.ipynb` through `05_typepro_shard_04.ipynb`: build five private shards.
- `06_merge_finalize.ipynb`: verify, merge, finalize, and publish the processed dataset.
- `07_train_and_infer.ipynb`: fine-tune CodeT5+ and evaluate the processed test split.
- `generate_notebooks.py`: regenerate the five-shard workflow.

Each build shard keeps only non-built-in function parameters. It builds a cached
third-party KB from imports in each project and stores detailed class structure
(package/module, bases, fields, and public method signatures) in recommendations.
The contrastive positive is always the annotation's `gttype`.

## Before uploading

1. Commit and push the current code to the repository/branch configured in the notebooks.
2. In Kaggle **Settings > Secrets**, create `KAGGLE_USERNAME` and `KAGGLE_KEY`.
3. Never paste either secret into a notebook or commit `kaggle.json`.

## Run order

1. Upload and run the five shard notebooks with Internet enabled and CPU/None accelerator.
2. Each shard publishes `KAGGLE_USERNAME/typepro-build-shard-XX` privately.
3. Run `06_merge_finalize.ipynb` after all five datasets exist.
4. Attach the resulting `typepro-python-contrastive` dataset to `07_train_and_infer.ipynb` and run with a GPU.

The merge refuses shards with another shard count/split or unattempted projects.

## Regenerate

```bash
python kaggle_notebooks/generate_notebooks.py --shards 5
```
