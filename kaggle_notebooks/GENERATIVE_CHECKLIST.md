# TypePro generative workflow checklist

This checklist is evidence-driven. A checked implementation item is not proof
that its external Kaggle job has completed; external items require a kernel
version, manifest, or exact Dataset file listing.

## Implementation

- [x] Ten logical shard notebooks mapped five per Kaggle account.
- [x] Fifteen physical partitions represented in `shard_merge_plan.json`.
- [x] Shard notebooks support same-account host auth and optional
  `TYPEPRO_PUBLISH_USERNAME` / `TYPEPRO_PUBLISH_KEY` Secrets.
- [x] Merge notebook supports optional `TYPEPRO_FINAL_USERNAME` /
  `TYPEPRO_FINAL_KEY` Secrets.
- [x] One isolated `knowledge_base.json` is built per project.
- [x] Project KB includes project types, imported types, functions/return
  values, type aliases, and re-export aliases.
- [x] Recommendations are restricted to the current project's KB and capped at
  top 10.
- [x] Generative examples contain all required tagged fields and exact label.
- [x] Project KBs are packaged in shards, merged, and copied into final output.
- [x] Training/inference notebook uses seq2seq label generation, not
  contrastive retrieval.

## Local gates

- [x] Full `codet5p_type_retrieval/tests` suite passes (80 passed, 1 Windows-only skip).
- [x] Notebook generation is reproducible with no unexpected diff.
- [x] Shard dry-run validates 10 notebooks and 15 partitions.
- [x] Merge dry-run validates exactly 15 Dataset inputs.

## Kaggle execution evidence

- [ ] All shard kernels pushed under their planned owners.
- [ ] All 15 physical shard versions completed successfully.
- [ ] Exact Dataset file listings show `raw_slices`, `project_status`, and
  `project_kb/*/knowledge_base.json` in every shard payload.
- [ ] Merge kernel completed under `duyvu1105`.
- [ ] Final Dataset `duyvu1105/typepro-python-generative` is listable.
- [ ] Final `manifest.json` passes `verify_dataset.py`.
- [ ] Final Dataset contains one retained KB for every completed project.
- [ ] Sampled final rows have 1..10 project-local recommendations and the exact
  ground-truth label.
