# TypePro Kaggle workflow: target masking rerun

Current workflow (2026-10-18): **21 independent physical partitions**, generated
from 10 logical shard templates, on three accounts. The table below supersedes
the historical two-account workflow documented later in this file.

| Runner / Dataset owner | Logical shards | Physical jobs | Visibility |
| --- | --- | ---: | --- |
| duyvu1105 | 00, 01 part 1, 02 (3 parts), 04, 05 | 7 | private |
| duymign | 01 part 2, 03 (3 parts), 06, 07 (2 parts) | 7 | public |
| vdduy1105 | 01 part 3, 08, 09 (5 parts) | 7 | public |

Final merge remains under `duyvu1105`. The authoritative inputs are the 21
entries in `shard_merge_plan.json`. Shard 2 retains 2/20, while 12/20 is replaced
by 12/40 and 32/40. Physical coordinates outside shard 1 and that shard 2 subdivision are preserved.

Shard 1 replaces its old `1/10` input with three disjoint coordinates:

| Part | Coordinate | Runner / Dataset owner | Kernel suffix | Visibility |
| --- | --- | --- | --- | --- |
| 1 | `1/30` | duyvu1105 | `shard-01-part-01` | private |
| 2 | `11/30` | duymign | `shard-01-part-02` | public |
| 3 | `21/30` | vdduy1105 | `shard-01-part-03` | public |

This divides projects by the existing hash, not by annotation or row. The union
equals the original shard, with no duplicate projects; project counts and runtimes
need not be identical. Candidate policy, revision lock and other shards are unchanged.
Each part authenticates as its own runner. Render only these three jobs with
`python kaggle_notebooks/commit_shard_versions.py --shard 1`; select one with
`--part 1`, `--part 2` or `--part 3`. Add `--push` only when authorized to run.
The old unsplit kernel is retired; do not schedule it alongside the three parts.
Old scheduler ledgers have a different job list: use a fresh `--state` or dry-run
`--new-run` rather than overwriting submission history. Do not push a full rerun
merely to start these three parts.

Final publication packages KBs with explicit full paths. Projects whose names
collide case-insensitively receive distinct hash suffixes in the archive; all
original KB contents are preserved. `project_kb_index.json` maps each original
`owner__repo` spelling to its published KB path. Consumers should use this index
when present, falling back to `project_kb/<owner>__<repo>/knowledge_base.json`
for older Datasets. The publisher waits for the published version number to
advance; `ready` from an older version does not establish publication success.
If only final publication needs retrying after a completed merge, dry-run
`python kaggle_notebooks/commit_merge_finalize.py --republish-from-merge-output`,
then use the same command with `--push`. This uses the latest completed
`duyvu1105/merge-dataset` output as a kernel input, verifies the final files,
and publishes without rebuilding or merging the shards again.
The two new kernels end in `-part-02-subpart-01` and `-part-02-subpart-02`;
their private Dataset slugs end in `-12-of-40` and `-32-of-40`, avoiding writes
from the retired 12/20 kernel. Render/push these with `--shard 2 --part 2`
and `--shard 2 --part 3`, respectively. Do not rerun part 1 for this split.
As authorized on 2026-09-08, 12/40 skips `visit-dav/visit-deps` before cloning
or KB construction. Its project status records the exclusion; no samples from
that project are exported. Other partitions have an empty skip list.
Split parts now have separate kernel IDs ending in `-part-01`, etc. Each
account starts at most five jobs, then submits remaining jobs when slots are free.
Local credentials map to `kaggle.json`, `kaggle2.json`, `kaggle3.json` in that
order. Never print keys or commit credentials.
Automatic resume is optional: if a previous Dataset lists successfully but its
archive cannot be downloaded, the notebook starts a fresh build. Downloaded
archives still require matching coordinates and retrieval schema before reuse.

```powershell
python kaggle_notebooks/generate_notebooks.py --shards 10 --runner-accounts duyvu1105 duymign vdduy1105 --dataset-owner duyvu1105
python kaggle_notebooks/commit_shard_versions.py
python -m pytest tests -q -p no:cacheprovider
```

For the complete rerun, use the scheduler instead of pushing all partitions
without a slot check. Dry-run first; it resolves GitHub main once, saves the
plan and renders all payloads without contacting Kaggle. No manual SHA is needed.

```powershell
python kaggle_notebooks/schedule_shards.py
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/schedule_shards.py --push --watch
```

The scheduler pins the source checkout to that commit, counts nonterminal jobs
across each account, reserves newly submitted slots, and keeps a durable ledger
at `typepro_kernel_versions/latest_run.json`. Reusing the same ledger retains
its saved SHA and avoids duplicate pushes. To start another run with the newest
GitHub main, dry-run with `--new-run`, then submit without that flag. The old
ledger is archived. Explicit `--revision SHA` (or `latest`) and `--state PATH`
remain supported, including resuming historical `rerun_state.json` ledgers.
An interrupted `submitting` entry requires inspecting the
remote version before any retry. The watcher exits after all 21 submissions;
submission is not proof of completed datasets. Verify manifests/file listings
before merge. Do not publish or train the final dataset automatically.

## Shared project KB and masked source

The resolved-context rerun uses
`context_policy_version=ast-context-v7-verified-signature-evidence`
and masking stamp `typepro-shared-kb-masked-source-v7-resolved-bounded-context`.
Current schema v17 (`typepro-project-kb-top10-generative-v17-catalog-fallback-audit`)
invalidates v16 raw slices so the missing-catalog export fix and complete caller
cache are actually rerun. Project-KB v7, masking and evidence policy stay unchanged.
Exporter summaries now distinguish empty slices, timeouts, exceptions by type,
and successful file-local catalog fallbacks. Target and resolved
function contexts preserve their leading docstrings. Caller contexts retain
their signatures (including parameter annotations) and docstrings alongside
the reduced body; target annotations remain masked in all copies. Opaque
callers retain their signature, docstring and exact call only. Project wildcard
imports resolve only when AST export analysis proves the binding. Literal
`__all__` and default public names are supported; unavailable modules, dynamic
exports, cycles, shadowing and competing definitions remain unresolved.
The retained-evidence policy also tracks operations on aliases and loop elements
of returned collections, collects verified module callers, and resolves calls in
their own lexical scope. A sibling lambda no longer suppresses a callee signature.
Project alias declarations (`NewType`, explicit `TypeAlias`, and verified implicit
typing expressions) enter the shared KB; only aliases used by retained value
dependencies enter slices. Name similarity influences candidate ranking only.
Explicit re-exports and in-project native/Git-mode-120000 symlinks map imports to
canonical source without guessing module names or following links outside the project.
Verified library imports can contribute signatures from a unique qualified KB
record (legacy records without module metadata apply only to root-package imports).
Known class receivers contribute signatures only; unknown receivers never use
short-name lookup. Literal boolean module branches are resolved statically;
runtime branches stay unresolved. Alias recognition includes project-class unions
and async typing forms. Candidate definitions retain comments belonging to selected
class members within the existing 8k budget. Larger definitions still use only
signatures and docstrings. `check_evidence_inventory.py` audits evidence in both
slices and candidates, including justified removals and explicit coverage limits.
Target and caller contexts reduce statements recursively inside control blocks,
retaining relevant conditions, loop inputs/updates and control transfers.
Unrelated blocks are removed. Related definitions enter the slice only after resolving an
unshadowed module-level function or a proven project import. Both caller
contexts and callees are checked against the AST catalog; a short-name match
never permits inserting a body. Unknown callees keep only the original call.
Resolved callees prefer signatures when relevant annotations are informative.
Missing/broad relevant annotations can supplement the signature with a reduced
body containing additional evidence. Uncertain binding/reduction keeps only
the signature, never the whole callee. Expansion stops at one hop. Target
functions with opaque dynamic/scope effects can still retain their whole body;
opaque callers retain the call instead of inserting the whole caller.

Receiver methods, nested callable scopes and opaque mutation remain unresolved
in this conservative implementation. Class name similarity supplies retrieval
evidence rather than adding a guessed class to the slice. Project class
recommendations select complete methods and their attribute/helper dependencies.
After target masking and member selection, candidate definitions of at most
8,000 Unicode characters remain unchanged. Larger definitions retain signatures
and docstrings; classes also retain bases and attribute declarations. If the
summary still exceeds 8,000 characters, signatures take priority and docstrings
retain only complete paragraphs that fit. If signatures alone exceed the budget,
whole trailing declarations are omitted; an oversized header or unparseable
source receives an omission comment. No code statement is cut in half. This is
a per-candidate character limit, not a token limit or total prompt budget.
Top-10 ranking is preserved. Shared KB
definitions remain complete and class method return annotations remain excluded.

Before publishing, each v6 shard audits every raw row for the policy stamps,
top-10 count, 8,000-character cap and provenance of inserted related functions.
Failure stops packaging/publication. `context_audit.json` records median, p95,
p99, maximum input character lengths and the 20 largest contexts. Large genuine
target/resolved functions are reported rather than silently truncated. No
tokenizer is run during shard creation.

Run `python -m typepro.audit.regressions --output outputs/audit/evidence/regressions.json`
to replay all nine supplied loss patterns. The JSON includes each check, rendered
slice, top-10 candidates and provenance. These are regression fixtures, not model
accuracy measurements or a verification of every row in an existing Dataset.

For a first batch of exactly five physical jobs per account, use a fresh
ledger and pass `--jobs-per-account 5` to both scheduler dry-run and push.
Do not run the unrestricted watcher while waiting for user authorization for
the remaining jobs. This selects 15 of the 21 partitions, preserving the plan.
The continuation uses `--skip-jobs-per-account 5` and a separate ledger only
after the user requests it.

Retrieval schema: `typepro-project-kb-top10-generative-v16-verified-signature-evidence`.
Build one KB per project and reuse it for every sample. The KB never reads a
function return annotation: it creates neither a candidate nor `returned_by`
metadata from one, and stored function signatures omit it. It retains candidates
from class definitions, imports, aliases, and executable return expressions such
as `return User()`. Mask the sample target in an in-memory source overlay before
slicing and retrieval.

Reuse project semantic analysis built from source flow without return annotation
seeds; create lightweight masked signature indexes and fresh slicing caches per
sample. Do not rebuild the project KB or semantic solver per sample. Mask target
signatures in copies of selected definitions before rendering the prompt; never
mutate the KB. Other annotations are retained.

Tests verify that changing source target annotations with the same fixed KB
preserves slices and ordered candidates, and prohibit per-sample KB/solver
rebuilding. Rows use
`target_masking_version=typepro-shared-kb-masked-source-v7-resolved-bounded-context`.

Old restored datasets fail the retrieval-schema check. Local completed-project
resume also requires a matching schema stamp on each status file, including
after an interrupted rebuild. Merge requires the new runtime schema and row
stamps, preventing mixed old/new partitions.

Repository checkout revisions are pinned in
`configs/project_revision_lock.json`, generated from the
published v13 rows. Shard notebooks process only projects in this lock and
fetch each exact 40-character commit before slicing. The runtime manifest
records the lock SHA-256 and source Dataset version. Regenerate the lock
deliberately with `build_project_revision_lock.py` when changing the project
cohort; do not silently refresh branch heads.

## Historical two-account workflow (reference only)


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
- `14_test_retrieval_ablation.ipynb`: rebuild only the current v12 test-project
  set with target-member matching and keyword-only propagation, then compare
  exact top-10 candidate recall without publishing a Dataset.
- `shard_account_plan.json`: notebook, kernel, owner, visibility and shard
  mapping.
- `shard_merge_plan.json`: the exact 16 Dataset inputs accepted by merge.
- `commit_shard_versions.py`: dry-run or push selected/all shard notebooks.
- `commit_merge_finalize.py`: dry-run, push, or check the merge kernel.
- `commit_data_analysis.py`: dry-run or push the token-analysis kernel.
- `commit_test_retrieval_ablation.py`: render, push or inspect the test-only
  retrieval comparison kernel.
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
python -m pytest tests -q -p no:cacheprovider
```

Render the token-analysis kernel locally without contacting Kaggle:

```bash
python kaggle_notebooks/commit_data_analysis.py
```

The analysis submission pins the local `HEAD` commit (override with
`--revision SHA`). That commit must be available on GitHub. The notebook
checks out the exact revision and records it and the input Dataset manifest
in `analysis_config.json`. Dry-run rendering does not read credentials.

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
`configs/test_projects.txt`. Unavailable projects (including those
with no parameter/return samples) are replaced by other successfully processed
projects, ranked deterministically with seed 13. A streaming preflight applies
the exact same sample filter as preprocessing, so failed or empty projects do
not count toward 100. The writer routes each sample directly into its final
split, avoiding a second full JSONL copy on Kaggle's working disk. Every sample in
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

The obsolete five-shard recovery utilities were removed. For the current
21-partition plan use `recover_shard_version.py` or rerun the exact partition
with `schedule_shards.py`; never mix historical `shard_count=5` outputs.

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
accelerate launch --multi_gpu typepro/training/generative.py \
  --data-dir /kaggle/input/typepro-python-generative \
  --output-dir /kaggle/working/codet5p-typepro-python \
  --train-samples 10000
```

In `12_train_and_infer.ipynb`, set `TRAIN_SAMPLES = 10000`. Leave it as `None`
to train on every training sample. The selected subset is reproducible for the
same `--seed`; requesting zero, a negative value, or more rows than available
is rejected.
