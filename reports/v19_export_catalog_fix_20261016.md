# Sửa lỗi export khi file vắng trong catalog — 16/10/2026

Đã xác định và sửa một lỗi cụ thể làm giảm mẫu ở v19: `alias_context()` tra `self.trees[path]` trong catalog không chứa file target, gây `KeyError` và bỏ annotation.

## Bằng chứng từ lần chạy v19

`project_status/*.json` của shard có trường `exporter_tail`. Trường này chứa phần cuối log và JSON tổng kết exporter, dù toàn bộ file `.log` không được publish.

Cả sáu project có số mẫu test giảm đều ghi `timed_out: 0` trong tổng kết annotation. Các đoạn log còn giữ lại có lỗi `KeyError` theo đường dẫn source; một số lỗi `FileNotFoundError` cũng tồn tại. Không thể coi toàn bộ số failed là timeout hoặc toàn bộ là cùng một exception vì log chỉ giữ phần cuối.

Catalog có thể thiếu file khi phân tích toàn project timeout và chuyển sang chế độ cục bộ, hoặc khi scanner bỏ qua thư mục `venv`/thư mục ẩn. Ví dụ `sara0871/-north-america-` ghi rõ project analysis timeout sau 300 giây, sau đó hai annotation lỗi `KeyError`; annotation timeout vẫn bằng 0.

## Thay đổi

`Python/export_slices.py` kiểm tra file target có trong catalog trước khi slice. Nếu thiếu, tạo catalog riêng từ đúng source đã masking của file đó cho lần export hiện tại. Không sửa catalog dùng chung, không quét lại toàn project, không suy đoán quan hệ liên file. Diagnostic ghi `component=catalog`, `mode=file_local`, `reason=target_file_not_indexed`.

Các đường chạy có file trong catalog giữ nguyên. Chính sách rút gọn context, docstring, alias, chữ ký đã xác minh và giới hạn candidate 8.000 ký tự vẫn áp dụng.

## Kiểm tra

- Bốn regression tái hiện `KeyError` trước sửa; sau sửa đều qua: tham số/return với catalog rỗng hoặc catalog của project không chứa target. Kiểm tra thêm masking, alias, docstring, chữ ký local và catalog dùng chung không bị thêm file fallback.
- Toàn bộ suite: **345 passed, 2 skipped**.
- Replay **302/302 mẫu thật** đã export được ở v18 từ sáu project, dùng source tại `source_commit` đã khóa và catalog project rỗng để kích hoạt nhánh lỗi. Tất cả tạo được slice có `<mask>` sau sửa.

| Project | Mẫu v18 được replay | Export slice sau sửa | Mẫu test v19 hiện có |
| --- | ---: | ---: | ---: |
| `zulip/zulip` | 124 | 124 | 13 |
| `mozilla/gecko-dev` | 89 | 89 | 28 |
| `apache/incubator-superset` | 57 | 57 | 13 |
| `dudengjin/python.two` | 21 | 21 | 2 |
| `rafallan/gestao_clientes` | 8 | 8 | 4 |
| `sara0871/-north-america-` | 3 | 3 | 1 |
| **Tổng** | **302** | **302** | **61** |

Kết quả replay lưu ở `reports/v19_catalog_fallback_replay_20261016.json`. Đây là kiểm chứng bước export slice với KB rỗng, chưa phải rerun toàn bộ retrieval/project KB/Kaggle và chưa xác nhận Dataset cuối phục hồi đúng 241 mẫu. Dataset v19 đã publish chưa thay đổi; cần build lại các shard liên quan rồi merge để đưa bản sửa vào Dataset mới.
