# Vì sao test v21 ít mẫu hơn v20

Kiểm tra ngày 2026-10-18, Dataset `duyvu1105/typepro-python-generative`.
Merge kernel `duyvu1105/merge-dataset` v25 đã COMPLETE, publish Dataset v21
private và đủ 21 input trong plan. Không có shard bị bỏ khỏi merge.

## Chênh lệch đã xác nhận

| Chỉ số | v20 | v21 |
| --- | ---: | ---: |
| Train | 44.861 | 42.168 |
| Validation | 3.671 | 3.373 |
| Test | 3.277 | 3.233 |
| Project test, không phân biệt hoa/thường | 100 | 100 |
| Raw slice trước finalize, toàn dataset | 51.829 | 48.785 |
| Row bị loại khi preprocess, toàn dataset | 20 | 11 |

V21 mất 126 target từng có trong test v20, thêm 82 target từ bốn project
thay thế: `3277 - 126 + 82 = 3233`, giảm ròng 44 mẫu. Khi đối chiếu đã loại
phần global row index khỏi ID fallback; index này thay đổi khi build lại và
không phải danh tính annotation. So sánh có giữ số lần xuất hiện, không dùng
set để làm mất các row trùng khóa. Project có hai cách viết hoa/thường được
tính chung khi kiểm tra số lượng 100 project.

| Project bị giảm | v20 | v21 | Giảm |
| --- | ---: | ---: | ---: |
| ekisu/dots | 26 | 4 | 22 |
| fabiosanches13/Cirq | 32 | 14 | 18 |
| MPI-Dortmund/transphire_transform | 78 | 61 | 17 |
| MGodgildieva/allennlp_NLP_hw4 | 13 | 0 | 13 |
| hackobi/AI-Scalpel-Trading-Bot | 108 | 96 | 12 |
| itselijahtai/kulgap | 9 | 0 | 9 |
| alexdong/mort | 72 | 64 | 8 |
| hosszubalazs/evil_snek | 8 | 0 | 8 |
| cympfh/fastcnn | 32 | 27 | 5 |
| jasperges/pose-thumbnails | 5 | 0 | 5 |
| jonasrauber/foolbox | 21 | 16 | 5 |
| kubeflow/kfserving | 14 | 11 | 3 |
| equinor/gordo-components | 74 | 73 | 1 |

Cả 13 project giữ đúng source commit như test v20. Lỗi không đến từ việc
checkout sang revision khác. Project status v21 ghi `SyntaxError` ở cả 13
project; tổng 128 annotation lỗi cú pháp, gồm cả annotation không có trong
test cũ. Chênh lệch target thực sự mất khỏi test cũ là 126.

## Lỗi trong bước lấy import evidence

`typepro/analysis/candidate_policy.py`, trong `source_evidence`, tạo biểu
thức từ tên import và qualified name trong KB rồi gọi:

```python
expression = ast.parse(spelling, mode='eval').body
```

KB được xây bằng cách quét file/package, nên tên module không phải lúc nào
cũng là biểu thức Python hợp lệ. KB thực của `ekisu/dots` trong v21 có:

- `numpy.typing.tests.data.pass.arithmetic.Object`: `pass` là từ khóa Python.
- `cv2.config-3.PYTHON_EXTENSIONS_PATHS`: `config-3` không phải tên thuộc tính hợp lệ.

Đã đọc KB đã publish, không tải repo, rồi tạo catalog tối thiểu có
`import numpy as np`. Gọi `source_evidence` tái hiện lỗi tại chính dòng trên:

```text
np.typing.tests.data.pass.ufunc_config.func1
                    ^^^^
SyntaxError: invalid syntax
```

Đây là phép tái hiện tối thiểu bằng KB thật và import giả lập, không phải
full-project replay. Log project đã ghi đúng các loại lỗi `invalid syntax`
và `invalid decimal literal` ở dòng 1. Bước import evidence mới được thêm
giữa code final v20 (`05a41eb`) và các shard mới (`41b434e`/`fbae9b8`).
Các tối ưu cache không thay đổi logic parse này.

`SyntaxError` chưa được bắt ở đây nên truyền ra exporter. Exporter bắt lỗi
ở cấp annotation, tăng `failed`, rồi bỏ row đó và chạy tiếp. Vì vậy job có
thể COMPLETE, project không có trường `error`, nhưng vẫn xuất 0 annotation.
Ví dụ `MGodgildieva/allennlp_NLP_hw4`: 13 annotation, 0 written, 13 SyntaxError,
0 timeout, 0 empty slice. Cả bốn project mất toàn bộ mẫu đều có cùng dạng
`SyntaxError`, không phải thiếu repo hay OOM.

## Vì sao danh sách project test cũng đổi

`typepro/data/split.py` chọn preferred project từ những project còn ít nhất
một raw row hợp lệ. Nếu thiếu, nó bổ sung project khác theo hash để đủ 100.
Bốn project mất hết mẫu, tổng 35 mẫu cũ, bị thay thế:

| Project bổ sung | Mẫu test v21 |
| --- | ---: |
| OptimoDevelopment/python_architecture | 27 |
| cabalamat/meowcat2 | 37 |
| gchrupala/ursa | 2 |
| road-master/media-archiver | 16 |

Chín project còn trong test mất thêm 91 mẫu. Vì vậy:
`3277 - 35 - 91 + 82 = 3233`. Hash file preferred-project list giống nhau
ở hai version, nhưng actual holdout khác nhau do tính khả dụng sau export.

Ở v21, audit `expected_written_counts.test=3233` trùng số row cuối cùng.
Sự thiếu hụt đã xuất hiện trước finalize ở bước export, không phải merge
21 partition bỏ mất một phần hay finalize tự cắt 44 row test.

## Bản sửa local ngày 2026-10-18

`source_evidence()` trong `typepro/analysis/candidate_policy.py` đã bắt
`SyntaxError` và `ValueError` tại đúng lệnh parse biểu thức import. Khi tên
không hợp lệ, chỉ bỏ qua bằng chứng import đó; annotation vẫn được export
và candidate vẫn được xét bởi các đầu điểm khác. Không thay công thức,
weight, threshold, ngân sách ký tự hay chính sách chọn test project.

Hai regression test dùng đúng dạng tên gây lỗi `pass` và `config-3` đều
thất bại với code cũ, rồi thành công sau bản sửa. Test đi qua cả
`source_evidence()` và `export_one()`, xác nhận import/direct hợp lệ giữ
nguyên, candidate lỗi vẫn nhận điểm khớp tên, KB không bị sửa, target được
mask và thay nhãn ẩn không làm đổi recommendation. Các test so sánh với
reference cũ trên đầu vào hợp lệ cũng thành công: 40 test liên quan passed.
Sau bổ sung sửa resume: toàn bộ suite workspace **413 passed, 2 skipped**;
checkout triển khai **412 passed, 2 skipped**. `git diff --check` không có lỗi whitespace.

Đợt repair chỉ chọn 10 physical partition có project test bị `SyntaxError`:
`0/10`, `1/30`, `21/30`, `2/20`, `3/30`, `13/30`, `4/10`, `5/10`, `6/10`, `9/30`.
Code triển khai được pin ở commit `495b1ebc10c59a21b5d0e9df340aefd3034db4b1`
trên nhánh `fix/import-evidence-retry-20261018`, nối tiếp bản tối ưu `fbae9b8`.
Generator có tùy chọn `force_projects=False` cho payload repair; các notebook
chuẩn vẫn giữ mặc định force. Khi resume cùng schema/policy/commit project,
`prepare.py` chạy lại project có `export_summary.exceptions_by_type.SyntaxError`
và giữ output của các project khác. Status cũ có summary null vẫn đọc được.
Nếu archive cũ không tải được, cơ chế fallback hiện có sẽ build lại partition.
Ledger và payload nằm tại `typepro_kernel_versions/test_repair_20261018/`;
không chạy lại 11 partition còn lại.

Ngày 2026-10-19 đã xác nhận cả 10 job repair COMPLETE, 10 Dataset lên version
mới và 11 Dataset còn lại không đổi. Cả 13 project hết `SyntaxError`, khôi phục
128 raw row tại cùng source commit. Merge kernel `duyvu1105/merge-dataset` v26
COMPLETE và đã publish Dataset v22 private từ đúng 21 inputs.

| Split | Mẫu trong v22 |
| --- | ---: |
| Train | 43.848 |
| Validation | 3.604 |
| Test | 3.277 |

Đối chiếu trực tiếp v22 với v20 theo multiset target ổn định: không thiếu,
không thừa target; nhãn và source commit của cả 3.277 mẫu đều khớp. Danh sách
project test không đổi. Các commit `fbae9b8`, `17197de`, `495b1eb` đã được
hợp nhất vào `main`; hai nhánh nêu trên chỉ ghi lại lịch sử triển khai.

Lỗi có thể ảnh hưởng cả train/validation. Chênh lệch tổng row toàn dataset
là 3.035; báo cáo này chỉ đã truy nguyên chi tiết 126 target test bị mất,
không gán toàn bộ giảm train/validation cho cùng nguyên nhân khi chưa audit.

## Bằng chứng

Metadata, target rút gọn và status lấy từ đúng Dataset version nằm trong
thư mục ignored `typepro_kernel_versions/merge_20261018/test_comparison`:

- `v20_metadata.json`, `v21_metadata.json`.
- `comparison.json`, `v20_targets.json`, `v21_targets.json`.
- `project_export_diagnosis.json` và các file `*_status.json`.
- `import_evidence_reproduction.json`, gồm expression lỗi và traceback.

Chỉ lưu metadata target, không lưu toàn bộ `test.jsonl`, không tải project
source trong lần chẩn đoán. Bằng chứng repair và v22 nằm trong thư mục ignored
`typepro_kernel_versions/merge_20261019/`: `repair_check.json`, `state.json`,
`final_manifest.json`, `test_comparison/comparison.json` và
`git_integration/result.json`. Không commit Dataset hoặc các output tạm này.
