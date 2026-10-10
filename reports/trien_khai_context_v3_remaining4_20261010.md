# Context v3: remaining four partitions

Verified: 2026-10-10T18:03:04.526623+07:00 (Asia/Saigon).

Source commit: `8eb10e358e30d55f9d41b6bad419af43e384b7a4` (same as the first 15 jobs).

Tests: **222 passed, 2 skipped**. Dry-run selects exactly four partitions. Scheduler checks account slots before each batch; maximum five active jobs per account.

| Account | Partition | Kernel/version | Status |
| --- | --- | --- | --- |
| duyvu1105 | 4/10 | [duyvu1105/typepro-python-shard-04 v14](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-04) | RUNNING |
| duyvu1105 | 5/10 | [duyvu1105/typepro-python-shard-05 v10](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-05) | RUNNING |
| duymign | 17/20 | [duymign/typepro-python-shard-07-part-02 v9](https://www.kaggle.com/code/duymign/typepro-python-shard-07-part-02) | RUNNING |
| vdduy1105 | 89/90 | [vdduy1105/typepro-python-shard-09-part-05 v11](https://www.kaggle.com/code/vdduy1105/typepro-python-shard-09-part-05) | RUNNING |

Submitted only 4/10, 5/10, 17/20 and 89/90. Together with the previous batch, all 19 physical partitions have been submitted. The first 15 jobs were not resubmitted.

Kernel versions/statuses confirm submission, not completed Dataset publication. No merge or training was started.

Ledger: `typepro_kernel_versions/recursive_context_20261010_remaining4.json`.
