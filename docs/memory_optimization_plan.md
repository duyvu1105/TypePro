# Kế hoạch giảm RAM cho pipeline shard

Ngày kiểm tra: 2026-10-17. Đây là báo cáo khảo sát và kế hoạch; chưa thay đổi
logic pipeline. Đã gửi một notebook chẩn đoán Kaggle riêng, mô tả bên dưới.

## Kết quả đo được và giới hạn kết luận

Đã chạy ba tiến trình Python độc lập trên Windows/Python 3.12.10, dùng cùng
thư mục `typepro/analysis` gồm 19 file Python. Đo RSS bằng `psutil`, lấy mẫu
mỗi 10 ms. Exporter thử 20 parameter có annotation, xuất thành công 20/20.
Chỉ số là đỉnh quan sát được, không bảo đảm bắt được mọi đỉnh rất ngắn.

| Công việc đo | Đỉnh RSS quan sát (MiB) | Phạm vi |
| --- | ---: | --- |
| Quét package KB | 33,85 | `scan_package` rồi ghi JSON; 124 record |
| Dựng project KB | 54,55 | Không có imported KB; 145 record |
| Khởi tạo exporter và export 20 annotation | 86,21 | Có project KB, index, catalog và retrieval |

Trong exporter, RSS sau import là 31,06 MiB; sau nạp KB là 32,35 MiB;
sau parse project là 49,68 MiB; sau 20 annotation là 83,62 MiB.

**Exporter lớn nhất trong phép thử này. Chưa xác định được tiến trình lớn nhất
trên các shard Kaggle.** Phép thử không có metadata toàn dataset, package lớn
như môi trường Kaggle, pip download, full shard hay toàn bộ đường chạy CLI
của import builder. Không suy ra mức RAM thực tế hoặc thứ hạng trên Kaggle
từ các con số local này. RSS tăng cũng chưa chứng minh rò rỉ bộ nhớ.

Script và dữ liệu đo thử local đã được xóa theo yêu cầu dọn file tạm.
Các số tổng hợp phía trên ghi lại kết quả đã quan sát, không phải số đo Kaggle.

### Phép thử Kaggle riêng cho project cuối log shard 8

Notebook private: `vdduy1105/typepro-asyncgrpc-memory-diagnostic`, version 2,
đã xác nhận trạng thái `COMPLETE`. Version 1 xuất đủ mẫu nhưng lỗi import
trong monitor; đã sửa generator và chạy lại, chỉ dùng số đo version 2.
Chỉ chọn `tsangpozheng/asyncgrpc`, project commit
`79ba732ab74d15ad02ef94763259298554198899`, pipeline commit
`fbae9b876998103c3ce81cb84064efb9aa22d21f` (cùng code shard 8 v22).
Đây là phép thử một project trong session mới; không tái hiện bộ nhớ nền
đã tích lũy sau 145 project của phiên cũ v21, và phiên cũ dùng pipeline trước
tối ưu cache. Không coi phép thử chạy thành công là bằng chứng loại trừ OOM
ở phiên cũ.

Notebook lấy RSS của kernel điều phối, `prepare.py` và các descendant mỗi
giây, đọc cgroup nếu có, in log mỗi 10 giây và lưu summary/output riêng.
Giữ nguyên selection/shard 8/10, masking, scoring và giới hạn xử lý. Không
publish Dataset, không thay version hay dừng các shard hiện tại. Generator,
receipt và log quản lý nằm trong thư mục ignored
`typepro_kernel_versions/asyncgrpc_memory_20261017`.

Kết quả version 2 trên Kaggle, Python 3.13, lấy mẫu RSS mỗi giây:

| Process / giai đoạn | Đỉnh RSS quan sát (MiB) |
| --- | ---: |
| `prepare.py --stage metadata` | 326,64 |
| `prepare.py --stage slice` (tiến trình cha) | 132,19 |
| Kernel notebook điều phối | 104,38 |
| `export_slices.py` | 80,76 |
| `project_kb.py` | 80,48 |
| `build_third_party_kb.py` | 77,06 |
| `pip` cao nhất | 46,85 |

Toàn lượt metadata và slice mất 83,577 giây, chưa tính setup môi trường.
Xuất 12/12 annotation, 0 failed, 0 timeout, monitor không lỗi.
Package `google` quét 3.000 file, tạo 8.313 record; KB project khoảng
20,95 MB (20.951.370 byte). Các giới hạn scan giữ nguyên như shard.

Cgroup ghi peak 3,773 GiB trên giới hạn 30 GiB; `oom=0`, `oom_kill=0`
cả trước và sau lần đo. Tổng RSS đồng thời cao nhất của cây process được
theo dõi là 430,85 MiB, không phải tổng các peak riêng lẻ. Bộ nhớ container
còn gồm page cache và các tiến trình khác ngoài cây được theo dõi; không
gán toàn bộ 3,773 GiB cho Python.

Trong phép thử Kaggle này, metadata process lớn nhất; trong giai đoạn slice,
tiến trình cha lớn hơn từng worker. Kết quả khác phép thử local nhỏ phía trên.
**Không tái hiện OOM khi chạy project riêng. Chưa xác định nguyên nhân phiên
shard cũ bị hủy sau 145 project.** Sampling 1 giây có thể bỏ lỡ đỉnh ngắn;
cgroup peak bổ sung đỉnh ở cấp container nhưng không quy cho PID cụ thể.

Số đo gốc đã lấy về chỉ gồm báo cáo chẩn đoán, không tải repo/metadata/dataset:
`typepro_kernel_versions/asyncgrpc_memory_20261017/output/summary.json`,
`process_memory.jsonl`, `peaks.json`, `initial_cgroup.json`, `packages.json`.

### Kiểm tra tích lũy qua nhiều project — kết quả kiểm tra 2026-10-18

Đã gửi notebook private riêng
`vdduy1105/typepro-shard08-sequential-memory-diagnostic`, version 2.
Version 1 dừng trước stage metadata do biến khởi tạo notebook sai kiểu;
đã sửa generator và kiểm tra kiểu/cú pháp các đoạn mã nhúng trước khi gửi v2.
API hiện xác nhận version 2 `CANCEL_ACKNOWLEDGED`, `failure_message` trống.
Đây là phiên bị hủy, không phải một lượt `COMPLETE` đủ 150 project.
Lượt này được cấu hình chạy đủ 150 project shard 8/10, đúng thứ tự,
giữ cùng một tiến trình cha `prepare.py` cho toàn bộ stage slice. Không chia
thành 150 lần gọi prepare riêng. Pipeline pin cùng commit `fbae9b8` như trên.

Wrapper chỉ quan sát ở đầu project, đầu/cuối subprocess và sau khi dọn repo.
Không thêm `gc.collect`, eviction hay dọn cache. Mỗi boundary lưu parent RSS,
descendant PID, cgroup usage/peak/events và `memory.stat` để phân biệt
`anon`, `file`, `shmem`, `slab`. Trace theo giây lưu project/phase hiện tại.
`project_order.json` kiểm tra đủ 150 project và asyncgrpc ở vị trí 146.

Không publish Dataset và không thay version các shard hiện có.
Receipt, generator và log nằm ở thư mục ignored
`typepro_kernel_versions/shard08_memory_sequence_20261017`. Chỉ lấy báo cáo
chẩn đoán từ Kaggle về máy, không tải clone, package cache hoặc dataset.

Bộ theo dõi nền đã ngừng hoạt động trước lần kiểm tra này; lần kiểm tra
2026-10-18 lấy lại trạng thái và console trực tiếp từ Kaggle. API không trả
output file nào của version 2 sau khi hủy, nhưng có console khoảng 7,34 MB.
Log chỉ còn đoạn từ giây 14.524,99 tới 22.004,41 của session; không có gần
bốn giờ đầu hoặc số đo sau dòng log cuối. File trong `output` cũ thuộc
version 1 lỗi khởi tạo, đã tách sang `v1_failed_output`; không dùng để phân
tích version 2.

Sau khi loại log lặp do progress output, khôi phục được 596 boundary event
và 247 mẫu định kỳ; có 75 mốc sau dọn repo, tương ứng project 71–145.

| Chỉ số sau mỗi project trong đoạn còn log | Đầu đoạn | Cuối đoạn |
| --- | ---: | ---: |
| RSS tiến trình cha, cùng PID 98 | 117,296875 MiB | 117,312500 MiB |
| Cgroup `anon` | 344,23 MiB | 366,79 MiB |
| Cgroup `file` | 5,45 GiB | 6,65 GiB |
| Cgroup tổng | 6,29 GiB | 7,72 GiB |

RSS cha tăng tổng cộng **16 KiB qua 75 mốc**, không thể hiện xu hướng giữ
nhiều RAM của worker sau mỗi project. Ở cả 75 mốc dọn repo, danh sách
descendant rỗng: các worker đã kết thúc, không còn tiến trình con bị giữ lại.

Cgroup tăng chủ yếu ở page cache (`file`, khoảng 1,21 GiB) và slab (khoảng
201 MiB); `anon` chỉ tăng khoảng 22,56 MiB trong đoạn này. Đỉnh cgroup ghi
nhận cao nhất là **10,54 GiB trên giới hạn 30 GiB**. Tất cả số đo còn lại
đều có `memory.events.max=0`, `oom=0`, `oom_kill=0`, `oom_group_kill=0`.
Đây là số đo trước lúc log ngừng; không khẳng định giá trị sau lần ghi cuối.

Tiến độ cuối: **145/150 project đã xử lý, 144 completed và 1 failed**.
Project thứ 146 là `tsangpozheng/asyncgrpc`; log lại dừng ở
`[kb:package:start] package=google`, giống phiên shard 8 cũ. Trước khi vào
import KB của project này, cha dùng khoảng 117,31 MiB, container khoảng
7,72 GiB, `anon` khoảng 366,79 MiB, OOM counter vẫn bằng 0.
Không có traceback kết thúc phiên hoặc thông báo OOM trong đoạn log nhận được.
Mốc log cuối khoảng 6 giờ 6 phút không chứng minh thời gian hủy thực tế.
Nguyên nhân project failed trước đó không có trong đoạn log còn lại.

**Kết luận:** dữ liệu đo được không ủng hộ giả thuyết worker giữ RAM cộng dồn
vào tiến trình cha rồi làm shard OOM. Đã tái hiện vị trí log bị ngắt ở
`asyncgrpc/google`, nhưng chưa xác định được nguyên nhân hủy. Vì không có
trace cuối cùng trong output, chưa loại trừ được một đỉnh RAM đột ngột sau
lần log cuối hoặc nguyên nhân khác ở cấp Kaggle. Bước khảo sát tiếp theo
nên tập trung vào package `google` ở project này và thông tin hủy từ Kaggle,
thay vì thay đổi candidate, cắt KB hoặc thêm ép GC khi chưa có bằng chứng.

Số liệu phân tích: `memory_trend_analysis.json`,
`v2_boundaries_from_console.json`, `v2_periodic_samples_from_console.json`
và `latest_log.json` trong thư mục chẩn đoán nêu trên. Chỉ lấy console và
báo cáo; không tải repo hay Dataset về máy.

## Các điểm giữ RAM xác nhận từ code

### 1. Tiến trình cha giữ metadata ngoài shard

`typepro/data/prepare.py`:

- `load_prepared_annotations` nạp cả train, validation và test thành list.
- `slice_projects` nhóm toàn bộ row vào `rows_by_project`.
- Sau đó mới lọc project theo selection, revision lock, shard và max-projects.
- Việc lọc chỉ thay đổi `projects`; `rows_by_project` vẫn giữ row ngoài shard.
- Row của project đã hoàn tất cũng tiếp tục nằm trong mapping.

Đây là bộ nhớ nền tồn tại đồng thời với mỗi subprocess. Chưa có số đo để
khẳng định tiến trình cha nhỏ hơn exporter.

### 2. Exporter giữ cấu trúc project và tạo dữ liệu theo target

`project_index.scan_project` giữ source và AST của mọi file trong project.
`Function_methods`, `FunctionCatalog` và `ProjectTypeAnalyzer` giữ thêm index,
catalog và tham chiếu vào các AST đó. Nhiều tham chiếu cùng AST không đồng
nghĩa có nhiều bản sao AST.

`export_slices.export_one` tạo các record đã mask theo target và dựng lại
index cho mỗi annotation. Phải giữ cơ chế mask này để tránh leak nhãn.
`add_parent_links` tạo liên kết ngược trên AST; cần đo lượng đối tượng còn
sống sau từng annotation để phân biệt dữ liệu đang dùng, chu kỳ chưa được
GC thu gom và bộ nhớ allocator chưa trả cho hệ điều hành.

Lưu ý: `export_one` hiện truyền một `ProjectAnalysisCache()` mới vào mỗi lần
export. Không được mặc định coi cache này tích lũy suốt toàn shard, cũng
không được chia sẻ cache giữa target nếu chưa chứng minh khóa có chứa đầy
đủ thông tin masking. Cache định nghĩa import và LRU BM25/candidate có vòng
đời khác, cần đo riêng số entry và dung lượng.

### 3. Import KB builder giữ record giữa các package

Trong vòng lặp package của `build_third_party_kb.main`, các biến
`runtime_records`, `stub_records`, `keyed`, `existing` có thể còn tham chiếu
đến package trước trong khi đang xử lý package tiếp theo. Các list thường
chia sẻ record, không phải tất cả đều sao chép sâu; tuy nhiên những tham
chiếu này vẫn có thể kéo dài thời gian sống của record cũ.

`write_json` dùng `json.dumps` rồi `write_text`: ngoài object còn có chuỗi
JSON đầy đủ và bộ đệm encode tạm thời. Một package lớn có thể tạo đỉnh cao
hơn phép thử local nhỏ.

### 4. Project KB builder giữ AST cùng toàn bộ record

`build_project_kb` giữ danh sách parsed của project trong khi thêm record
import. `imported_records` trả về toàn bộ record import; phép trải list tạo
thêm danh sách tham chiếu. Khi ghi kết quả lại tạo chuỗi JSON đầy đủ.
Copy AST của class/function là một điểm cần profile, nhưng chưa thay đổi
vì nó phục vụ loại bỏ return annotation và có thể ảnh hưởng output.

### 5. Những tài nguyên không nên nhầm với RAM tích lũy

Ba giai đoạn import KB, project KB và export chạy tuần tự bằng subprocess
riêng cho mỗi project. Khi subprocess kết thúc, RAM của nó được hệ điều
hành thu hồi. Repo, wheel, JSON KB và log giữ trên đĩa không đồng nghĩa
Python còn giữ chúng trong heap. Cần xét thêm page cache ở mức container.
`run_logged` chỉ giữ 4.000 ký tự cuối, không giữ toàn bộ log trong RAM.

## Thứ tự triển khai đề xuất

### Bước 0 — đo đúng tiến trình trên Kaggle

Thêm monitor vào ranh giới subprocess của `run_logged`, ghi artifact chẩn
đoán riêng, không thêm trường vào row Dataset:

- Project, phase, PID, command rút gọn không chứa secret, elapsed và exit code.
- RSS của tiến trình cha, child trực tiếp và từng descendant, lấy mẫu 1 giây;
  ghi tổng hợp khoảng 10 giây và tại đầu/cuối mỗi phase, flush ra đĩa.
- Cgroup `memory.current`, `memory.peak`, `memory.max`, `memory.events` khi
  được phép đọc; lưu chênh lệch `oom`/`oom_kill` trước và sau phase.
- Phân biệt tổng RSS có thể đếm trùng shared pages với bộ nhớ thực của
  container; dùng PSS nếu hệ thống hỗ trợ. Không cộng các đỉnh ở những
  thời điểm khác nhau để suy ra đỉnh đồng thời.
- Chụp số record, source bytes, AST nodes và kích thước cache tại những mốc
  chọn lọc. Chỉ bật `tracemalloc` cho một lần tái hiện riêng, vì nó tăng RAM
  và thời gian, không dùng số đo đó làm baseline RSS sản xuất.

Đo project `abmazhr/lets_talk` và `tsangpozheng/asyncgrpc` từ đúng revision
lock và cùng môi trường package. Không kết luận package `google` gây OOM
chỉ vì đó là dòng cuối log. API status/failure_message cần thu thập bên
ngoài notebook; monitor trong notebook không thể bảo đảm ghi log sau khi
cả container bị dừng.

### Bước 1 — giảm bộ nhớ nền của tiến trình cha

Sau khi tính xong danh sách project bằng đúng logic hiện tại, chỉ giữ row
của các project được chọn. Lưu riêng annotation count cần cho status/log;
bỏ row của project sau khi mọi nhánh skip/success/failure đã xử lý xong.
Giải phóng `project_rows` và biến row cuối sau khi ghi task nếu không còn dùng.

Đợt này giảm RAM trong lúc subprocess chạy, chưa loại bỏ đỉnh khi đọc metadata.
Nếu số đo cho thấy đỉnh đọc metadata đáng kể, làm tiếp đọc hai lượt hoặc
stream: lượt đầu chỉ lấy tên project để giữ nguyên validation/selection,
lượt sau giữ row của project được chọn theo đúng thứ tự split và row cũ.
Không bỏ kiểm tra revision lock hoặc missing project ngoài ý muốn.

### Bước 2 — thu hẹp vòng đời dữ liệu package và ghi JSON tuần tự

Đưa xử lý một package vào hàm riêng, chỉ trả summary; khi hàm kết thúc không
còn record package trước bị biến local của vòng lặp giữ lại. Giữ nguyên thứ
tự package, file, record, cách deduplicate và ưu tiên stub/runtime.

Dùng `json.dump` hoặc `JSONEncoder.iterencode` với cùng tùy chọn serialization
vào file tạm rồi atomic replace. Mục tiêu bỏ chuỗi JSON khổng lồ; object
record vẫn còn trong RAM. So sánh byte-for-byte để xác nhận định dạng không đổi.
Áp dụng tương tự cho project KB và project index nếu số đo xác nhận có lợi.

### Bước 3 — tối ưu exporter theo profile

Đây là phần có rủi ro thay đổi output cao hơn, nên làm sau hai bước trên:

- Đo riêng AST/catalog, mask record, dựng index, import analyzer và retrieval.
- Thử thu gom chu kỳ ở ranh giới annotation trong thí nghiệm riêng; đo cả
  RAM lẫn thời gian, không mặc định gọi `gc.collect()` liên tục sẽ có lợi.
- Xem xét chia sẻ dữ liệu bất biến và chỉ tạo bản record mới khi masking làm
  thay đổi nội dung. Phải giữ thứ tự record, index và phạm vi che target.
- Chỉ thay chính sách dung lượng cache sau khi kiểm tra việc eviction/recompute
  không đổi kết quả. Không tái sử dụng cache theo source chưa mask cho target khác.
- Không bỏ AST/file/candidate, cắt KB hay giảm ngưỡng retrieval để chữa RAM.

## Điều kiện chấp nhận trước khi chạy lại shard

1. Cùng revision lock, package KB đầu vào, thứ tự project và cấu hình hiện tại.
2. So sánh chính xác KB/index JSON hoặc hash nội dung; raw row, candidate,
   thứ tự, definition, prompt và số row phải giống baseline.
3. Điểm candidate phải giống cả biểu diễn float, không chỉ gần bằng nhau.
4. Diagnostics có thời gian/timestamp được so sánh riêng; không dùng toàn bộ
   file có timestamp làm điều kiện hash đầu ra ngữ nghĩa.
5. Kiểm tra annotation mask và giữ cách ly target; kiểm tra resume/skip/failure.
6. Chạy differential tests và toàn bộ pipeline tests trước Git/Kaggle push.
7. Benchmark baseline/optimized trong subprocess độc lập, cùng máy và input;
   báo peak của cả container, từng process, elapsed và mức dao động qua các lần.
8. Kiểm tra merge với shard cũ; không thay schema/policy/revision lock chỉ vì
   thay cách quản lý bộ nhớ. Chỉ công bố mức giảm RAM sau khi có số đo.
