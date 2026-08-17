# TypePro Kaggle notebooks

This directory contains the two-account, ten-shard workflow for the Python
parameter-only dataset. Every shard has its own notebook and Kaggle kernel; no
half-shard or replacement-residue Dataset participates in the current merge.

## Current artifacts

- `00_test_dataset_owner.ipynb`: optional credential/owner smoke test.
- `01_typepro_shard_00.ipynb` through `10_typepro_shard_09.ipynb`: ten
  standalone CPU shard notebooks.
- `11_merge_finalize.ipynb`: validate and merge exactly ten attached Datasets,
  preprocess the splits, verify them, and publish the final private Dataset.
- `12_train_and_infer.ipynb`: fine-tune and evaluate after attaching the final
  Dataset.
- `shard_account_plan.json`: notebook, kernel, owner, visibility and shard
  mapping.
- `shard_merge_plan.json`: the exact ten Dataset inputs accepted by merge.
- `commit_shard_versions.py`: dry-run or push selected/all shard notebooks.
- `commit_merge_finalize.py`: dry-run, push, or check the merge kernel.
- `generate_notebooks.py`: the only source for generated notebook changes.

Do not edit generated notebooks manually when the change belongs in
`generate_notebooks.py`.

## Ownership contract

| Shards | Runner and Dataset owner | Kernel pattern | Visibility |
| --- | --- | --- | --- |
| `00-04` | `duyvu1105` | `duyvu1105/typepro-python-shard-XX` | private |
| `05-09` | `duymign` | `duymign/typepro-python-shard-XX` | public |

The merge runs under `duyvu1105` and publishes the private Dataset
`duyvu1105/typepro-python-contrastive`. The second account's shards must remain
public so the final owner can attach them.

Each shard manifest must report its own `shard_index`, `shard_count=10`, no
missing projects, and every selected project attempted. The merge rejects
different counts, duplicate coordinates, gaps and overlaps.

## Candidate retrieval

Each shard keeps non-built-in function parameters and builds a cached
stdlib/third-party KB. Candidate retrieval unions exact imports, declarations
visible in the masked slice, project classes and aliases, lexical/structural
retrieval, `.pyi`/Typeshed symbols, project call/data flow, fixtures and common
factory/framework idioms. The target parameter annotation is never used as a
retrieval signal.

`RETRIEVAL_SCHEMA_VERSION` is embedded in every shard notebook and stored in
`runtime_manifest.json`. A restored Dataset with a missing/different version is
ignored, forcing fresh `raw_slices`; a retry with the same version resumes
completed projects. This prevents a new retrieval implementation from silently
reusing old recommendations.

The two known very long projects use a 600-second per-annotation timeout:

- `home-assistant/home-assistant`
- `Opentrons/opentrons`

A timed-out annotation is logged and omitted while the project and shard keep
running. This timeout is why the workflow can remain at ten shards.

## Credentials

Never print, paste or commit API keys. Local ignored credentials default to:

- `kaggle.json` for `duyvu1105`;
- `kaggle2.json` for `duymign`.

The push scripts verify the credential username. Inside Kaggle, same-account
host authentication is the default. Optional explicit Secrets are
`TYPEPRO_PUBLISH_USERNAME` + `TYPEPRO_PUBLISH_KEY`; merge accepts
`TYPEPRO_FINAL_USERNAME` + `TYPEPRO_FINAL_KEY`. A complete legacy pair uses
`kaggle==1.7.4.2` so host OAuth cannot silently replace the requested owner.

## Generate and test

Generate all ten shard notebooks plus merge/train:

```bash
python kaggle_notebooks/generate_notebooks.py --shards 10 --runner-accounts duyvu1105 duymign --dataset-owner duyvu1105
```

Dry-run all ten standalone kernels without contacting Kaggle:

```bash
python kaggle_notebooks/commit_shard_versions.py
```

The summary must contain shards `0..9` exactly once, ten distinct notebook
paths/kernel IDs, five jobs per account, private `00-04`, public `05-09`, and
`shard_count=10` throughout.

Run the repository tests after generator/publisher changes:

```bash
python -m pytest codet5p_type_retrieval/tests -q -p no:cacheprovider
```

## Push shards

Push/start all ten jobs only after reviewing the dry-run:

```bash
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_shard_versions.py --push
```

Use explicit credential paths when needed:

```bash
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_shard_versions.py --credential "duyvu1105=D:\secure\duyvu.json" --credential "duymign=D:\secure\duymign.json" --push
```

Retry only selected shard kernels:

```bash
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_shard_versions.py --shard 2 --shard 8 --push
```

Each kernel slug is shard-specific, so a retry creates a new version only for
that shard and cannot overwrite another shard's notebook config.

## Merge and publish

After all ten Dataset versions are listable, dry-run the merge payload:

```bash
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_merge_finalize.py
```

Then push and check it:

```bash
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_merge_finalize.py --push
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_merge_finalize.py --check-status
```

The merge kernel `duyvu1105/typepro-merge-10-shards` receives exactly these
attached inputs:

- private `duyvu1105/typepro-build-shard-00` through `...-04`;
- public `duymign/typepro-build-shard-05` through `...-09`.

It reads attached `/kaggle/input` data and never downloads shard payloads at
runtime. It validates manifests before running `merge_shards.py`, finalization,
dataset verification and publication.

## Recovery

If slicing/publishing fails, rerun only that standalone shard. Compatible
partial state resumes automatically. If the completed archive remains in a
saved kernel version but publication failed, dry-run then use:

```bash
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/recover_shard_version.py --source-version 8=2 --push
```

Here shard `08` is restored from version `2` of
`duymign/typepro-python-shard-08`. Replace the version with the actual saved
version. Recovery only republishes verified completed output; it does not
rebuild recommendations.

`restore_shard_02_from_v8.py` and `resume_shards_from_versions.py` are legacy
five-shard history utilities. Their `shard_count=5` outputs must never be mixed
with this ten-shard workflow.

## Completion order

1. Generate artifacts and run tests.
2. Dry-run and inspect the ten shard payloads.
3. Push the ten standalone kernels with the correct two credentials.
4. Verify all ten Dataset manifests and file listings.
5. Push/check `11_merge_finalize.ipynb` under `duyvu1105`.
6. Attach the final Dataset to `12_train_and_infer.ipynb` and run training.
