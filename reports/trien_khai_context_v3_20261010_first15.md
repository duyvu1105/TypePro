# Triển khai context v3: 15 job đầu

Xác minh: 2026-10-10T16:18:56.846528+07:00 (Asia/Saigon).

Source commit: `8eb10e358e30d55f9d41b6bad419af43e384b7a4`.

Kiểm thử: **222 passed, 2 skipped**. Dry-run đúng 15 partition, 5/account. Scheduler kiểm tra slot; không vượt 5 active/account.

Policy: `ast-context-v3-recursive-signature-first`; retrieval schema: `typepro-project-kb-top10-generative-v12-recursive-signature-first`.

| Account | Partition | Kernel/version | Status |
| --- | --- | --- | --- |
| duyvu1105 | 0/10 | [duyvu1105/typepro-python-shard-00 v15](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-00) | RUNNING |
| duyvu1105 | 1/10 | [duyvu1105/typepro-python-shard-01 v15](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-01) | RUNNING |
| duyvu1105 | 2/20 | [duyvu1105/typepro-python-shard-02-part-01 v14](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-02-part-01) | RUNNING |
| duyvu1105 | 12/40 | [duyvu1105/typepro-python-shard-02-part-02-subpart-01 v11](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-02-part-02-subpart-01) | RUNNING |
| duyvu1105 | 32/40 | [duyvu1105/typepro-python-shard-02-part-02-subpart-02 v10](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-02-part-02-subpart-02) | RUNNING |
| duymign | 3/30 | [duymign/typepro-python-shard-03-part-01 v12](https://www.kaggle.com/code/duymign/typepro-python-shard-03-part-01) | RUNNING |
| duymign | 13/30 | [duymign/typepro-python-shard-03-part-02 v13](https://www.kaggle.com/code/duymign/typepro-python-shard-03-part-02) | RUNNING |
| duymign | 23/30 | [duymign/typepro-python-shard-03-part-03 v14](https://www.kaggle.com/code/duymign/typepro-python-shard-03-part-03) | RUNNING |
| duymign | 6/10 | [duymign/typepro-python-shard-06 v18](https://www.kaggle.com/code/duymign/typepro-python-shard-06) | RUNNING |
| duymign | 7/20 | [duymign/typepro-python-shard-07-part-01 v12](https://www.kaggle.com/code/duymign/typepro-python-shard-07-part-01) | RUNNING |
| vdduy1105 | 8/10 | [vdduy1105/typepro-python-shard-08 v16](https://www.kaggle.com/code/vdduy1105/typepro-python-shard-08) | RUNNING |
| vdduy1105 | 9/30 | [vdduy1105/typepro-python-shard-09-part-01 v15](https://www.kaggle.com/code/vdduy1105/typepro-python-shard-09-part-01) | RUNNING |
| vdduy1105 | 19/30 | [vdduy1105/typepro-python-shard-09-part-02 v14](https://www.kaggle.com/code/vdduy1105/typepro-python-shard-09-part-02) | RUNNING |
| vdduy1105 | 29/90 | [vdduy1105/typepro-python-shard-09-part-03 v13](https://www.kaggle.com/code/vdduy1105/typepro-python-shard-09-part-03) | RUNNING |
| vdduy1105 | 59/90 | [vdduy1105/typepro-python-shard-09-part-04 v12](https://www.kaggle.com/code/vdduy1105/typepro-python-shard-09-part-04) | RUNNING |

Đã submit đúng 15 job, ghim cùng source commit trên. Bốn partition chưa push trong đợt này, chờ người dùng yêu cầu: **4/10, 5/10 (duyvu1105), 17/20 (duymign), 89/90 (vdduy1105)**.

Version/status kernel xác nhận submission, chưa xác nhận Dataset đã hoàn tất publish. Chưa merge hoặc train.

Ledger local: `typepro_kernel_versions/recursive_context_20261010_first15.json`.
