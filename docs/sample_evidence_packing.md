# Sample-local evidence and model-specific context packing

Shard export creates `evidence_bundle` (`typepro-evidence-v1`) while the source
AST and project KB are available on Kaggle. The bundle travels unchanged through
preprocessing into each train/validation/test row. Consumers need only the split
JSONL files; they do not load project KBs. The full KB remains in published
artifacts for the existing provenance/reproducibility contract.

## Export contract

- One mandatory `core` contains the masked target plus its existing reduced
  callee/alias/control/data closure. Arbitrary source statements are not split.
- Resolved callers can become optional atomic blocks, including the caller's
  argument dependencies, aliases and enclosing control flow. Only exact,
  standalone matches in the rendered slice are separated; ambiguous matches or
  recursive target copies remain in the mandatory core.
- Up to ten ranked candidates carry their selected class/member definitions
  **before character truncation**. Each also has a short identity-only display
  and, when smaller, an intermediate AST reduction preserving method return,
  control and explicit-parameter dependencies. The original definition remains
  available as its full level; reducer fallbacks are retained whole.
  Existing candidate ranking and legacy character-limited fields stay available.
- Blocks include identity, kind, priority, dependency IDs and source provenance.
  Identity/provenance are audit metadata, not extra prompt text. No label enters
  selection or packing. Target annotations are masked in every returned copy.

Candidate/member selection is still conservative AST selection. A class that
cannot be safely reduced can be large; its complete definition is optional and
its identity can still fit. Required source/control evidence is never replaced
by an invented type fact. There is no claim that this selection is optimal for
accuracy; measure the tradeoff on held-out projects before changing weights.

## Packing contract

Training and inference share `typepro.shared.context_packing`. The input budget
is `input_length - label_length`, including system prompt and model chat template.
The packer retains required dependency closures, reserves candidate identities
in rank order, then attempts caller blocks and full candidate definitions by
priority, trying reduced method evidence before complete definitions. Every
attempt measures the complete rendered prompt with the active
tokenizer. Definitions and source blocks are retained whole or omitted.

If required evidence exceeds the budget, `ContextBudgetError` identifies the
sample and required token count. Increase the budget or explicitly filter such
samples after auditing; they are never silently dropped. Train and inference
must use the same budget and packing version. Old rows without bundles retain
their historical prefix behavior, explicitly reported as `legacy-prefix`.

SQLite caches under `packed_context_cache/` bind the exact source bundle, packing
policy, tokenizer backend/vocabulary, special tokens, initialization config,
system prompt, chat template and budget. Changing labels does not change packing.
Length grouping uses the same packed sequence as the training collator.
Inference predictions include selected/omitted block IDs and summary-only IDs.

Run a tokenizer-only audit from the repository root; no model weights or KB
download is required:

```powershell
python -m typepro.audit.packing --input DATA/train.jsonl --model-name Qwen/Qwen2.5-Coder-1.5B-Instruct --input-length 8192 --label-length 64 --report outputs/packing-qwen.json
```

The audit reports token quantiles, omitted/summary-only blocks, legacy rows and
mandatory overflows. It exits nonzero on mandatory overflow. A limited smoke
audit (`--limit 100`) does not establish corpus-wide coverage or model accuracy.

## Migration and Kaggle

Retrieval schema v18 (`typepro-project-kb-top10-generative-v18-sample-evidence`)
invalidates old raw slices. Publishing/merge validate bundles and reject a mix
of v18 and legacy shards. v17 frozen KBs remain reusable only with matching
source commit, KB v7, context policy and provenance checks; raw rows are always
regenerated. Changing the row format does not require downloading KBs locally.

The first launch selects five physical jobs per account (15 total), preserving
the complete 21-input plans. The remaining six partitions must be rebuilt under
v18 before final merge. Use a new ledger for this run:

```powershell
python kaggle_notebooks/schedule_shards.py --revision FULL_PUSHED_COMMIT_SHA --jobs-per-account 5 --state typepro_kernel_versions/evidence_v18_first15.json
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/schedule_shards.py --revision FULL_PUSHED_COMMIT_SHA --jobs-per-account 5 --state typepro_kernel_versions/evidence_v18_first15.json --push --watch
```

Submission does not establish dataset completion. Verify actual kernel versions,
statuses and published manifests before merging. No final merge/train job is
started by this launch.
