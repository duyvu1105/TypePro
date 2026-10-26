# Graph context baseline verification

Baseline source SHA: `a498310a55833428e67e63f3c94b8b9a8a33ed92`.
The initial main HEAD already equals the historical v24 source. The tracked tree
is identical, so no rollback of algorithms, helpers or independent fixes is needed.
No historical artifacts, checkpoints, predictions or credentials were modified.
The existing untracked implementation plan is preserved and recorded here.

On 2026-10-26:

- v24 launch config, dataset manifest source SHA and all three split SHA256 hashes
  agree (44,764 train, 3,694 validation, 3,277 test).
- `.venv/bin/python -m pytest tests -q -p no:cacheprovider`: 480 passed, 53.00s.
  System Python's installed pytest fails on import; the project environment works.
- Three-account notebook generation produces no tracked diff.
- Shard submission dry-run validates all 21 physical coordinates, 7 per account;
  no remote job was submitted.
- Context policy is `ast-context-v7-verified-signature-evidence`.

This report commit is the experiment baseline checkpoint; its parent is the
unmodified v24 source above. There is no additional output-affecting retained diff.
Full source/dependency-locked re-export comparison needs original checked-out
project sources and frozen dependency KBs; split hash verification does not claim
that comparison was performed. Experiment results must distinguish that limit.
