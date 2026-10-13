# Triển khai giữ bằng chứng: bốn job còn lại

Source commit: [dcf3794d814f11e091f27dd9bf8cb30cc6e476f5](https://github.com/duyvu1105/TypePro/commit/dcf3794d814f11e091f27dd9bf8cb30cc6e476f5), cùng phiên bản với 15 job đầu.

Kiểm thử trước push: **341 passed, 2 skipped**. Dry-run xác nhận đúng bốn partition **4/10, 5/10, 17/20, 89/90**, không trùng 15 job trước. Scheduler kiểm tra slot toàn account và giới hạn tối đa 5 job đang hoạt động/account.

Policy: `ast-context-v7-verified-signature-evidence`; retrieval schema: `typepro-project-kb-top10-generative-v16-verified-signature-evidence`; project KB v7.

Ledger local: `typepro_kernel_versions/verified_evidence_20261013_remaining4.json`.

Đã gửi đủ bốn job trong đợt này. Kết hợp với 15 job trước, toàn bộ **19/19 partition** đã được gửi với cùng source commit. Lúc kiểm tra **15:39 ngày 13/10/2026 (Asia/Saigon)**, cả bốn job mới đều `RUNNING`; trạng thái chi tiết của 15 job trước không được kiểm tra lại đầy đủ trong báo cáo này.

Lệnh tiếp tục an toàn với cùng ledger:

```powershell
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/schedule_shards.py --revision dcf3794d814f11e091f27dd9bf8cb30cc6e476f5 --skip-jobs-per-account 5 --state typepro_kernel_versions/verified_evidence_20261013_remaining4.json --push --watch
```

Nếu ledger có trạng thái `submitting`, cần đối chiếu version thực tế trước khi tiếp tục. Version/status kernel xác nhận việc gửi job; chưa xác nhận Dataset đã hoàn tất publish. Không chạy merge hoặc train trong đợt này.

<!-- VERIFIED_SUBMISSIONS -->

| Account | Partition | Kernel/version | Status | Verified (UTC) |
| --- | --- | --- | --- | --- |
| duyvu1105 | 4/10 | [duyvu1105/typepro-python-shard-04 v15](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-04) | RUNNING | 2026-10-13T08:39:23.304755+00:00 |
| duyvu1105 | 5/10 | [duyvu1105/typepro-python-shard-05 v11](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-05) | RUNNING | 2026-10-13T08:39:23.661332+00:00 |
| duymign | 17/20 | [duymign/typepro-python-shard-07-part-02 v10](https://www.kaggle.com/code/duymign/typepro-python-shard-07-part-02) | RUNNING | 2026-10-13T08:39:24.015381+00:00 |
| vdduy1105 | 89/90 | [vdduy1105/typepro-python-shard-09-part-05 v12](https://www.kaggle.com/code/vdduy1105/typepro-python-shard-09-part-05) | RUNNING | 2026-10-13T08:39:24.366313+00:00 |
