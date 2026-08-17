# TypePro on Cloud Run

This deployment builds all ten TypePro shards with Cloud Run Jobs, checkpoints
durable output to Cloud Storage, then merges and verifies the final dataset.
One Workflow execution waits for all shard tasks before starting finalization.

Deployment defaults are recorded in `config.json`. From the repository root:

```powershell
.\cloud_run\deploy.ps1 -RunId production-v1 -Execute
```

The shard job has ten tasks, runs at most two concurrently under the region's
memory quota, and uses `CLOUD_RUN_TASK_INDEX` as the deterministic shard index.
A task restores its previous GCS checkpoint on retry. The final
archive is written to:

```text
gs://project-7df9f963-9fe0-4b76-b3d-typepro/runs/production-v1/final/typepro-python-contrastive.zip
```

After the workflow finishes, download and checksum-verify the latest dataset:

```powershell
python cloud_run\download_dataset.py --output-dir typepro_python_contrastive
```

Or select a specific run:

```powershell
python cloud_run\download_dataset.py --run-id production-v1 --output-dir typepro_python_contrastive
```

The downloaded directory is directly suitable for
`codet5p_type_retrieval/publish_kaggle.py`. Kaggle credentials are deliberately
not stored in Cloud Run or Cloud Storage.
