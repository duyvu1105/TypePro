# Triển khai context v2 — 15 job đầu tiên

Xác minh: 2026-10-10T12:54:08+07:00 (Asia/Saigon).

Source commit: [50d7aa70c3baaf1aed0d10bd28c5d9d8db37d248](https://github.com/duyvu1105/TypePro/commit/50d7aa70c3baaf1aed0d10bd28c5d9d8db37d248).

Kiểm thử ban đầu: **203 passed, 2 skipped**; sau sửa resume: **204 passed, 2 skipped**. Dry-run đủ 19 partition và xác nhận đợt đầu đúng 15 job, 5/account.

14 payload ghim source commit trên. Riêng 2/20 retry ghim commit `2f24dc9e46a426e01049ddacdba285eba64824b1` để xử lý download resume 404; thuật toán context và retrieval schema v11 không đổi. KB đầy đủ; mỗi candidate definition tối đa 16.000 ký tự. Không đưa thân hàm chưa resolve vào slice. Publisher audit toàn bộ raw rows trước khi đóng gói.

| Account | Tọa độ | Kernel/version | Trạng thái |
| --- | --- | --- | --- |
| duyvu1105 | 0/10 | [duyvu1105/typepro-python-shard-00 v14](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-00) | RUNNING |
| duyvu1105 | 1/10 | [duyvu1105/typepro-python-shard-01 v14](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-01) | RUNNING |
| duyvu1105 | 2/20 | [duyvu1105/typepro-python-shard-02-part-01 v13](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-02-part-01) | RUNNING |
| duyvu1105 | 12/40 | [duyvu1105/typepro-python-shard-02-part-02-subpart-01 v10](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-02-part-02-subpart-01) | RUNNING |
| duyvu1105 | 32/40 | [duyvu1105/typepro-python-shard-02-part-02-subpart-02 v9](https://www.kaggle.com/code/duyvu1105/typepro-python-shard-02-part-02-subpart-02) | RUNNING |
| duymign | 3/30 | [duymign/typepro-python-shard-03-part-01 v11](https://www.kaggle.com/code/duymign/typepro-python-shard-03-part-01) | RUNNING |
| duymign | 13/30 | [duymign/typepro-python-shard-03-part-02 v12](https://www.kaggle.com/code/duymign/typepro-python-shard-03-part-02) | RUNNING |
| duymign | 23/30 | [duymign/typepro-python-shard-03-part-03 v13](https://www.kaggle.com/code/duymign/typepro-python-shard-03-part-03) | RUNNING |
| duymign | 6/10 | [duymign/typepro-python-shard-06 v17](https://www.kaggle.com/code/duymign/typepro-python-shard-06) | RUNNING |
| duymign | 7/20 | [duymign/typepro-python-shard-07-part-01 v11](https://www.kaggle.com/code/duymign/typepro-python-shard-07-part-01) | RUNNING |
| vdduy1105 | 8/10 | [vdduy1105/typepro-python-shard-08 v15](https://www.kaggle.com/code/vdduy1105/typepro-python-shard-08) | RUNNING |
| vdduy1105 | 9/30 | [vdduy1105/typepro-python-shard-09-part-01 v14](https://www.kaggle.com/code/vdduy1105/typepro-python-shard-09-part-01) | RUNNING |
| vdduy1105 | 19/30 | [vdduy1105/typepro-python-shard-09-part-02 v13](https://www.kaggle.com/code/vdduy1105/typepro-python-shard-09-part-02) | RUNNING |
| vdduy1105 | 29/90 | [vdduy1105/typepro-python-shard-09-part-03 v12](https://www.kaggle.com/code/vdduy1105/typepro-python-shard-09-part-03) | RUNNING |
| vdduy1105 | 59/90 | [vdduy1105/typepro-python-shard-09-part-04 v11](https://www.kaggle.com/code/vdduy1105/typepro-python-shard-09-part-04) | RUNNING |

**Đã submit 15 job.** Bốn job chưa submit, chờ người dùng yêu cầu: 4/10, 5/10 (duyvu1105), 17/20 (duymign), 89/90 (vdduy1105).

2/20 v12 đã ERROR trước slicing do archive Dataset cũ trả 404 khi resume. Generator đã sửa để download resume thất bại thì build mới; chỉ retry job này thành v13. Tổng số partition vẫn là 15; đã kiểm tra account chỉ có 4 job hoạt động trước retry.

Version/status kernel xác nhận submission; chưa xác nhận Dataset đã hoàn tất publish. Không chạy merge hoặc train trong đợt này.

Ledger local: `typepro_kernel_versions/resolved_context_20261010_first15.json`.

Chi tiết sửa, phạm vi kiểm tra và số đo hồi quy: [kiem_tra_context_v2_20261010.md](kiem_tra_context_v2_20261010.md).
