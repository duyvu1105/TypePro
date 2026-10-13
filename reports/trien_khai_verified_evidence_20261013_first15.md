# Triển khai giữ bằng chứng: 15 job đầu

Source commit: [dcf3794d814f11e091f27dd9bf8cb30cc6e476f5](https://github.com/duyvu1105/TypePro/commit/dcf3794d814f11e091f27dd9bf8cb30cc6e476f5).

Kiểm thử trước push: **341 passed, 2 skipped**. Dry-run xác nhận đúng 15 partition, 5 job mỗi account, theo cùng thứ tự của đợt trước. Scheduler kiểm tra số job đang hoạt động trên từng account và giới hạn tối đa 5 job/account.

Policy: `ast-context-v7-verified-signature-evidence`; retrieval schema: `typepro-project-kb-top10-generative-v16-verified-signature-evidence`; project KB v7. Các payload ghim đúng source commit nêu trên.

Bốn partition chưa chạy trong đợt này: **4/10, 5/10, 17/20, 89/90**. Kế hoạch đầy đủ 19 partition và merge inputs được giữ nguyên.

Version và trạng thái kernel bên dưới xác nhận việc gửi job; chưa xác nhận Dataset đã hoàn tất publish. Không chạy merge hoặc train trong đợt này.

Ledger local: `typepro_kernel_versions/verified_evidence_20261013_first15.json`.

Lệnh tiếp tục an toàn nếu quá trình gửi bị gián đoạn sau một submission đã được ghi nhận:

```powershell
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/schedule_shards.py --revision dcf3794d814f11e091f27dd9bf8cb30cc6e476f5 --jobs-per-account 5 --state typepro_kernel_versions/verified_evidence_20261013_first15.json --push --watch
```

Tái sử dụng đúng ledger để tránh gửi trùng job. Nếu ledger có trạng thái `submitting`, cần đối chiếu version thực tế trước khi tiếp tục.

<!-- VERIFIED_SUBMISSIONS -->

| Account | Partition | Kernel/version | Status | Verified (UTC) |
| --- | --- | --- | --- | --- |
| duyvu1105 | 0/10 | [duyvu1105/typepro-python-shard-00 v16](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-00) | RUNNING | 2026-10-13T06:19:34.014080+00:00 |
| duyvu1105 | 1/10 | [duyvu1105/typepro-python-shard-01 v16](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-01) | RUNNING | 2026-10-13T06:19:34.390138+00:00 |
| duyvu1105 | 2/20 | [duyvu1105/typepro-python-shard-02-part-01 v15](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-02-part-01) | RUNNING | 2026-10-13T06:19:34.765620+00:00 |
| duyvu1105 | 12/40 | [duyvu1105/typepro-python-shard-02-part-02-subpart-01 v12](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-02-part-02-subpart-01) | RUNNING | 2026-10-13T06:19:35.110545+00:00 |
| duyvu1105 | 32/40 | [duyvu1105/typepro-python-shard-02-part-02-subpart-02 v11](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-02-part-02-subpart-02) | RUNNING | 2026-10-13T06:19:35.464252+00:00 |
| duymign | 3/30 | [duymign/typepro-python-shard-03-part-01 v13](https://www.kaggle.com/code/duymign/typepro-python-shard-03-part-01) | RUNNING | 2026-10-13T06:19:35.836081+00:00 |
| duymign | 13/30 | [duymign/typepro-python-shard-03-part-02 v14](https://www.kaggle.com/code/duymign/typepro-python-shard-03-part-02) | RUNNING | 2026-10-13T06:19:36.190009+00:00 |
| duymign | 23/30 | [duymign/typepro-python-shard-03-part-03 v15](https://www.kaggle.com/code/duymign/typepro-python-shard-03-part-03) | RUNNING | 2026-10-13T06:19:36.568737+00:00 |
| duymign | 6/10 | [duymign/typepro-python-shard-06 v19](https://www.kaggle.com/code/duymign/typepro-python-shard-06) | RUNNING | 2026-10-13T06:19:36.929927+00:00 |
| duymign | 7/20 | [duymign/typepro-python-shard-07-part-01 v13](https://www.kaggle.com/code/duymign/typepro-python-shard-07-part-01) | RUNNING | 2026-10-13T06:19:37.286580+00:00 |
| vdduy1105 | 8/10 | [vdduy1105/typepro-python-shard-08 v17](https://www.kaggle.com/code/vdduy1105/typepro-python-shard-08) | RUNNING | 2026-10-13T06:19:37.649766+00:00 |
| vdduy1105 | 9/30 | [vdduy1105/typepro-python-shard-09-part-01 v16](https://www.kaggle.com/code/vdduy1105/typepro-python-shard-09-part-01) | RUNNING | 2026-10-13T06:19:38.008554+00:00 |
| vdduy1105 | 19/30 | [vdduy1105/typepro-python-shard-09-part-02 v15](https://www.kaggle.com/code/vdduy1105/typepro-python-shard-09-part-02) | RUNNING | 2026-10-13T06:19:38.388137+00:00 |
| vdduy1105 | 29/90 | [vdduy1105/typepro-python-shard-09-part-03 v14](https://www.kaggle.com/code/vdduy1105/typepro-python-shard-09-part-03) | RUNNING | 2026-10-13T06:19:38.743381+00:00 |
| vdduy1105 | 59/90 | [vdduy1105/typepro-python-shard-09-part-04 v13](https://www.kaggle.com/code/vdduy1105/typepro-python-shard-09-part-04) | RUNNING | 2026-10-13T06:19:39.136398+00:00 |
