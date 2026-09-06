# TypePro Kaggle notebooks

This directory contains the two-account, ten-logical-shard workflow for the
Python generative dataset (function parameters and returns; built-in
annotations kept in the current rerun). Every shard has exactly one notebook and one
Kaggle kernel. Shards `02` and `07` run as two versions of their existing
kernel; shards `03` and `09` run as three versions. Each version publishes a
disjoint physical Dataset partition.

## Current artifacts

- `00_test_dataset_owner.ipynb`: optional credential/owner smoke test.
- `01_typepro_shard_00.ipynb` through `10_typepro_shard_09.ipynb`: ten
  standalone CPU shard notebooks.
- `11_merge_finalize.ipynb`: validate and merge exactly 16 attached Datasets,
  preprocess the splits, verify them, and publish the final private Dataset.
- `12_train_and_infer.ipynb`: fine-tune and evaluate after attaching the final
  Dataset.
- `13_data_analysis.ipynb`: measure token lengths and truncation impact before
  choosing a training context length.
- `shard_account_plan.json`: notebook, kernel, owner, visibility and shard
  mapping.
- `shard_merge_plan.json`: the exact 16 Dataset inputs accepted by merge.
- `commit_shard_versions.py`: dry-run or push selected/all shard notebooks.
- `commit_merge_finalize.py`: dry-run, push, or check the merge kernel.
- `commit_data_analysis.py`: dry-run or push the token-analysis kernel.
- `generate_notebooks.py`: the only source for generated notebook changes.

Do not edit generated notebooks manually when the change belongs in
`generate_notebooks.py`.

## Ownership contract

| Shards | Runner and Dataset owner | Kernel pattern | Visibility |
| --- | --- | --- | --- |
| `00-04` | `duyvu1105` | `duyvu1105/typepro-python-shard-XX` | private |
| `05-09` | `duymign` | `duymign/typepro-python-shard-XX` | public |

The merge runs under `duyvu1105` and publishes the private Dataset
`duyvu1105/typepro-python-generative`. The second account's shards must remain
public so the final owner can attach them.

Unsplit manifests use physical coordinate `index/10`. Split shard versions use
`index + 10 * part_index` over `10 * part_count`, giving `02` and `07`
coordinates over `/20`, and `03` and `09` coordinates over `/30`. Every part
reports no missing projects and shows every selected project was attempted.
The merge rejects duplicate coordinates, gaps, and overlaps.

## Candidate retrieval

Each shard slices function parameters (and returns in the current rerun),
keeps built-in annotations, and builds an isolated KB
for every project. Candidate retrieval unions exact imports, declarations
visible in the masked slice, project classes and aliases, lexical/structural
retrieval, `.pyi`/Typeshed symbols, project call/data flow, fixtures and common
factory/framework idioms. It then filters and ranks only records stored in that
project's KB and emits at most 10 recommendations. The target annotation is
never used as a retrieval signal. Each KB retains project classes/type aliases,
imported library types, functions with return types, and re-export aliases.

Final JSONL rows are generative CodeT5 examples, not contrastive pairs. Their
`input` contains `[TARGET_NAME]`, `[TARGET_FUNCTION]`,
`[INTERPROCEDURAL_SLICE]`, and `[RECOMMENDATION_TYPES]` entries represented by
`[TYPE]` plus `[DEFINITION]`; `label` is the exact `gttype`. The final Dataset
also contains `project_kb/<owner>__<repo>/knowledge_base.json` for every
completed project.

`RETRIEVAL_SCHEMA_VERSION` is embedded in every shard notebook and stored in
`runtime_manifest.json`. A restored Dataset with a missing/different version is
ignored, forcing fresh `raw_slices`; a retry with the same version resumes
completed projects. This prevents a new retrieval implementation from silently
reusing old recommendations.

Every project uses a 120-second per-annotation timeout. A timed-out annotation
is logged and omitted while the project and shard keep running. Applying the
deadline globally prevents a previously unknown pathological slice from
stalling an entire shard indefinitely.

Work before annotation export is bounded too: each missing-package download is
limited to 900 seconds, the complete per-project KB phase to 1800 seconds, and
the shared project scan/index/semantic analysis to 300 seconds. A KB deadline
keeps the files already generated and continues with that partial KB. An
analysis deadline switches the project to file-local slicing, so either slow
phase degrades candidate recall instead of blocking the shard.

Project indexing parses every source file once and emits function, class and
call-site indexes from the shared ASTs. Function uses carry module/class-qualified
names to keep common methods such as `__init__` and `update` separate. Stdlib KB
generation uses Typeshed directly when a matching stub exists instead of also
scanning the runtime implementation. Every annotation is traced so the parent
hard-kill timer stays armed; normal progress prints every 50 records.

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

Generate all ten shard notebooks plus merge/train/analysis:

```bash
python kaggle_notebooks/generate_notebooks.py --shards 10 --runner-accounts duyvu1105 duymign --dataset-owner duyvu1105
```

Dry-run all ten standalone kernels without contacting Kaggle:

```bash
python kaggle_notebooks/commit_shard_versions.py
```

The summary must contain ten distinct notebook paths and kernel IDs, plus 16
distinct Dataset IDs. Split parts repeat their logical shard's kernel ID because
they are pushed as successive versions of the existing notebook.

Run the repository tests after generator/publisher changes:

```bash
python -m pytest codet5p_type_retrieval/tests -q -p no:cacheprovider
```

Render the token-analysis kernel locally without contacting Kaggle:

```bash
python kaggle_notebooks/commit_data_analysis.py
```

Push it after reviewing the rendered payload:

```bash
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_data_analysis.py --push
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

Retry selected logical shard kernels (all configured parts of each):

```bash
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_shard_versions.py --shard 2 --shard 8 --push
```

Each kernel slug is shard-specific. Every configured part creates a successive
version of that same existing kernel and cannot overwrite another shard's
notebook config. Use `--part N` with one `--shard` to retry only one 1-based
part.

## Merge and publish

The finalizer now selects exactly **100 projects with usable preprocessed
samples** for test. It prioritizes the 103 repository identifiers extracted from
the published Python baseline artifacts in
`reports/typepro_test_audit/projects.txt`. Unavailable projects (including those
with no parameter/return samples) are replaced by other successfully processed
projects, ranked deterministically with seed 13. Selection happens after sample
filtering, so failed or empty projects do not count toward 100. Every sample in
a selected project goes to test; all other projects are partitioned into train
and validation, with no project overlap.

`test_projects.txt` in the final Dataset is the actual selected list.
`test_split_audit.json` and the manifest record retained artifact projects,
supplements, unavailable preferred projects, and counts. This is an adjusted
benchmark, not a reconstruction of the paper's original 11,029 annotations.
The merge uses the existing 18 physical inputs in `shard_merge_plan.json`
(including the three subdivisions of partition 29), as explicitly authorized
for this rerun; it does not repush shard notebooks.

After all 10 Dataset shards are listable, dry-run the merge payload:

```bash
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_merge_finalize.py
```

Then push and check it:

```bash
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_merge_finalize.py --push
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_merge_finalize.py --check-status
```

The merge kernel `duyvu1105/merge-dataset` receives exactly 16 attached inputs:

- private `duyvu1105/typepro-build-shard-{00,01,02,03,04,12,13,23}`;
- public `duymign/typepro-build-shard-{05,06,07,08,09,17,19,29}`.

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
2. Dry-run and inspect the 10 shard payloads.
3. Push the ten shard kernels with the correct two credentials.
4. Verify all 10 Dataset manifests and file listings.
5. Push/check `11_merge_finalize.ipynb` under `duyvu1105`.
6. Run `13_data_analysis.ipynb` to choose and document the context length.
7. Attach the final Dataset to `12_train_and_infer.ipynb` and run training.

## Limit training samples

`train_generative.py` uses the entire train split when `--train-samples` is
omitted. To train on a deterministic random subset while keeping the complete
validation split, run for example:

```bash
accelerate launch --multi_gpu codet5p_type_retrieval/train_generative.py \
  --data-dir /kaggle/input/typepro-python-generative \
  --output-dir /kaggle/working/codet5p-typepro-python \
  --train-samples 10000
```

In `12_train_and_infer.ipynb`, set `TRAIN_SAMPLES = 10000`. Leave it as `None`
to train on every training sample. The selected subset is reproducible for the
same `--seed`; requesting zero, a negative value, or more rows than available
is rejected.
