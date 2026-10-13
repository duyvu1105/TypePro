# Kiểm chứng giữ bằng chứng kiểu — 2026-10-13

## Kết quả và phạm vi

**Cả 9 nhóm thiếu sót người dùng gửi đã lấy lại bằng chứng cần thiết:**
9/9 fixture tái hiện và 9/9 replay trên source upstream khóa theo Git SHA đều qua.
Full suite: **299 passed, 2 skipped**. Hai test bỏ qua phụ thuộc nền tảng POSIX.

Kết quả này kiểm chứng slice/candidates. Chưa rebuild Dataset trên Kaggle, chưa
chạy inference và chưa đo accuracy. Replay upstream dùng file target và các file
dependency được liệt kê, không phải toàn bộ repo hoặc checkout lịch sử của v15/v18.
Ví dụ Mort upstream dùng caller `capture`; fixture giữ mẫu `load_screenshots` người
dùng đã mô tả. Cả hai giữ annotation `targets: List[Dict]` và docstring target.

## Đối chiếu trên cùng fixture

`83fc661` là snapshot so sánh; riêng commit đó thay đổi packaging/publishing KB.
HEAD trước các sửa local là `3aa78b282adbf0ab94d96cabb999d72955aa53cb`.
Hai baseline được chạy trong thư mục tạm từ `git archive`, cùng checker và fixture.

| Trường hợp / bằng chứng bắt buộc | 83fc661 | HEAD trước sửa | Hiện tại | Source upstream |
| --- | --- | --- | --- | --- |
| Superset: `for fk`, gán theo key và `.pop()` | Qua | Thiếu | Qua | Qua |
| Workshop: `as_strings(range(1, 3))` | Qua | Thiếu | Qua | Qua |
| Workshop: khai báo NewType và `get_username(UserId(4606))` | Qua | Thiếu | Qua | Qua |
| Foolbox: `ModelAndData` và định nghĩa tuple | Qua | Thiếu | Qua | Qua |
| Subhub: chữ ký `retrieve_stripe_plan(plan_id: str)` qua symlink | Qua | Thiếu | Qua | Qua |
| python_types: `expect_user_mapping({'test': User()})` | Qua | Thiếu | Qua | Qua |
| Advent of Code: `make_grid(claims: typing.List[Claim])` dù có lambda | Qua | Thiếu | Qua | Qua |
| Nicecream: đủ hai call site `fetch_bookmark` qua wildcard import | Qua | Thiếu | Qua | Qua |
| Mort: docstring và chữ ký caller có `targets: List[Dict]` | Một phần¹ | Thiếu | Qua | Qua |

¹ Fixture tối giản ở snapshot cũ giữ docstring nhưng không sinh chữ ký caller;
vì vậy baseline đạt 8/9 theo điều kiện kiểm tra hiện tại. Đây không phải replay
nguyên mẫu Dataset cũ và không phủ định chữ ký trong mẫu v15 người dùng cung cấp.

Trong fixture Foolbox có thêm 15 class không liên quan: `ModelAndData` đứng đầu
top-10. Nó không được chèn vào slice chỉ vì tên gần giống `fmodel_and_data`.

## Nguyên nhân và thay đổi

- Reducer cũ không nối biến phần tử vòng lặp với collection được trả về.
  Nay giữ thao tác trên collection/phần tử/alias, kể cả loop lồng nhau và call
  có thể mutate phần tử. Reassignment tách phần tử khỏi quan hệ cũ; các block
  và mutation trên collection không liên quan vẫn bị loại.
- Catalog cũ bỏ caller cấp module. Nay resolve module scope và giữ exact call,
  dependency đối số, guard cần thiết; không kéo toàn bộ module vào slice.
- Resolver cũ từ chối mọi call khi hàm bao ngoài có lambda. Nay caller/callee
  được xét theo scope của call; sibling lambda không làm mất chữ ký callee.
  Call bên trong lambda/nested callable chưa được chứng minh vẫn bị từ chối.
- Legacy class index đã có NewType/alias ngầm, nhưng shared KB thiếu các dạng
  này. Nay `type_aliases.py` xác minh typing/builtin bindings và đưa khai báo
  hợp lệ vào KB. Runtime indexing, constructor bị shadow và alias bị rebind
  không thành candidate alias. Khai báo alias liên quan trực tiếp và import
  đổi tên của nó được giữ trong slice; similarity chỉ tác động ranking.
- Symlink/re-export được ánh xạ về source thật. Chỉ nhận native symlink hoặc
  Git mode 120000; bỏ link ra ngoài project, từ chối cycle/rebinding/dynamic
  effects ở module trung gian. Không dùng fallback theo tên ngắn để chèn body.
- Diagnostics ghi provenance của caller/alias và lý do giữ collection operation.
  Publisher audit yêu cầu provenance khi caller/alias đã được chèn. Ví dụ caller
  bị từ chối được giới hạn 20/mẫu và có tổng số khi vượt giới hạn, tránh phình raw rows.

Các tối ưu tiếp tục được kiểm tra: giảm AST đệ quy, signature-first, một hop,
docstring, top-10, candidate tối đa 8.000 ký tự, shared AST/KB bất biến và target
masking trước retrieval. Candidate lớn dùng chữ ký/docstring, không cắt ngang code.

## Bằng chứng có thể mở và chạy lại

- [Fixture hiện tại](evidence_regressions_20261013.json): từng check, slice,
  candidates, diagnostics và SHA-256 implementation.
- [Fixture ở 83fc661](evidence_regressions_83fc661_20261013.json).
- [Fixture ở HEAD trước sửa](evidence_regressions_head_before_changes_20261013.json).
- [Replay upstream](evidence_upstream_replay_20261013.json): mỗi repo có full Git
  SHA, source URL, hash từng file, check và output. Fingerprint implementation
  trùng với report fixture hiện tại.
- [Regression tests](../codet5p_type_retrieval/tests/test_evidence_preservation.py):
  39 case mới gồm 9 mẫu, 9 phép thay annotation target và các test đối chứng.
- JUnit full suite nằm ở `typepro_kernel_versions/evidence_tests.xml` (output local).

```powershell
python codet5p_type_retrieval/check_evidence_regressions.py --output reports/evidence_regressions_20261013.json
python codet5p_type_retrieval/check_evidence_sources.py --manifest reports/evidence_upstream_replay_20261013.json --output reports/evidence_upstream_replay_20261013.json
python -m pytest codet5p_type_retrieval/tests -q -p no:cacheprovider
python kaggle_notebooks/commit_shard_versions.py
```

Hai checker trả exit code khác 0 khi bất kỳ case nào không qua. Checker upstream
dùng manifest để giữ nguyên revision. Code tải về chỉ được parse, không import
hoặc thực thi. Source replay kiểm tra file target và dependency tối thiểu; chưa
đo thay đổi ranking khi attach đầy đủ mọi file/KB thư viện của Dataset lịch sử.

## Phiên bản và kiểm tra workflow

- Policy: `ast-context-v6-retained-type-evidence`.
- Retrieval schema: `typepro-project-kb-top10-generative-v15-retained-type-evidence`.
- Project KB schema: `typepro-project-kb-v6-verified-aliases`.
- Target masking stamp giữ v7; candidate budget 8.000 ký tự Unicode.
- Generate qua generator; dry-run **19 jobs, 7/6/6**. Account/merge plans không
  có diff; giữ nguyên toàn bộ tọa độ và visibility. `git diff --check` qua.
- Raw/resume output cũ không tương thích policy/schema mới, tránh trộn slices.
- Các thay đổi ở working tree; chưa commit/push Git hoặc Kaggle.

Giới hạn còn lại: dynamic exports/receivers, closure phức tạp và alias tạo từ
runtime không được đoán. Bộ test xác nhận các mẫu đã nêu, không chứng minh mọi
chương trình Python hoặc mọi dự đoán model đều đúng.
