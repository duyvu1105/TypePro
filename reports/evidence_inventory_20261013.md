# Danh mục bằng chứng cũ–mới, 2026-10-13

Đã kiểm tra 31 tình huống trên snapshot `83fc6619175a52f9f59e00a238e1e821563abf75` và working tree sau sửa. Mỗi tình huống xét riêng slice và candidate definitions. Kết quả hiện tại: **31/31 thỏa chính sách**, gồm **22 trường hợp giữ bằng chứng hữu ích, 7 loại bỏ hợp lý, 1 đánh đổi do giới hạn 8k, 1 giới hạn có ở cả bản cũ lẫn bản mới**. Đây không phải 31 lỗi đã được khắc phục.

JSON cũ có `passed=20/31` vì các điều kiện kiểm tra của chính sách mới được áp vào code cũ, bao gồm masking, giới hạn độ dài và yêu cầu loại lookup không an toàn. Không dùng con số này để kết luận độ chính xác mô hình tăng từ 20 lên 31. Bảng so sánh dựa trên nội dung bằng chứng thực tế.

## Kiểm tra theo nhóm

| Nhóm | Bằng chứng phải kiểm tra | Kết quả và phân biệt |
| --- | --- | --- |
| Đối số thực tế | `range(...)`, dict chứa `User()`, `str(...)` | Giữ caller và biểu thức đối số cụ thể. |
| Chữ ký caller/callee | `List[Claim]`, `plan_id: str`, `targets: List[Dict]`, chữ ký thư viện và receiver | Giữ quan hệ đã xác minh; bổ sung chữ ký cho thư viện và receiver rõ kiểu. |
| Alias/NewType | `UserId`, `ModelAndData`, `Trivia`, `Awaitable`, `TypeAlias` | Giữ tên và định nghĩa; alias chưa có dependency được xác minh nằm trong candidates. |
| Thao tác trong target | Vòng lặp sửa dictionary trong `foreign_keys` | Giữ thao tác trên phần tử và alias của collection trả về; loại log không liên quan. |
| Tài liệu mô tả | Docstring có ví dụ list chứa dictionary; comment của class/member | Giữ docstring và comment của member được chọn trong giới hạn độ dài; loại comment của member bị pruning. |
| Retrieval và giới hạn độ dài | Có type và có quan hệ với target là hai điều khác nhau | Không dùng candidate trùng tên để đoán callee; giữ nguyên top-10 và giới hạn 8.000 ký tự. |

## Từng tình huống

Cột kênh dưới đây ứng với bằng chứng đại diện `evidence`. JSON có `evidence_channels` cho từng mẩu bằng chứng bắt buộc, cùng nguyên văn slice, definitions, diagnostics và kết quả kiểm tra masking, tính bất biến của dữ liệu nguồn, giới hạn độ dài.

| Case | Cũ | Mới | Phân loại và lý do |
| --- | --- | --- | --- |
| `superset_collection` | slice | slice | **Giữ bằng chứng hữu ích**. Giữ vòng lặp sửa phần tử mapping của collection trả về. |
| `workshop_range` | slice | slice | **Giữ bằng chứng hữu ích**. Giữ đối số thực tế `range(1, 3)`, không ép collection thành list. |
| `workshop_newtype` | slice | slice+candidates | **Giữ bằng chứng hữu ích**. Giữ lời gọi `UserId(...)` và định nghĩa NewType. |
| `foolbox_tuple_alias` | slice | candidates | **Giữ bằng chứng hữu ích**. Tên và định nghĩa `ModelAndData` có trong candidates; không chèn vào slice chỉ vì tên giống nhau. |
| `subhub_symlink` | slice | slice | **Giữ bằng chứng hữu ích**. Giữ `plan_id: str` qua import và symlink trong project đã được xác minh. |
| `mapping_constructor` | slice | slice | **Giữ bằng chứng hữu ích**. Giữ literal dict và lời gọi `User()` trong caller. |
| `adventofcode_lambda` | slice | slice | **Giữ bằng chứng hữu ích**. Giữ `claims: List[Claim]`; lambda cùng scope không che lời gọi `make_grid`. |
| `nicecream_wildcards` | slice | slice | **Giữ bằng chứng hữu ích**. Giữ caller của `fetch_bookmark` và schema qua wildcard import có export được xác minh. |
| `mort_documented_caller` | slice | slice | **Giữ bằng chứng hữu ích**. Giữ docstring mô tả list chứa browser dictionaries và chữ ký caller `targets: List[Dict]`. |
| `actual_str` | slice | slice | **Giữ bằng chứng hữu ích**. Giữ đối số thực tế `str(42)`. |
| `external_root_contract` | slice | slice | **Giữ bằng chứng hữu ích**. Bổ sung lại chữ ký từ explicit import đúng root package và KB record duy nhất. |
| `external_submodule_alias` | không có | slice | **Giữ bằng chứng hữu ích**. Bổ sung import có alias/submodule khi KB có `module` hoặc `qualified_name` chính xác. |
| `external_wrong_submodule` | slice | không có | **Loại hợp lý**. Loại lookup trùng tên: KB của root package không chứng minh được `extlib.other.decode`. |
| `receiver_constructed` | slice+candidates | slice | **Giữ bằng chứng hữu ích**. Giữ chữ ký khi `obj` được tạo từ class xác định, không mở rộng thân method. |
| `receiver_self` | slice+candidates | slice | **Giữ bằng chứng hữu ích**. Giữ chữ ký của method được gọi qua `self` trong class sở hữu đã được xác minh. |
| `receiver_nominal_contract` | slice+candidates | slice | **Giữ bằng chứng hữu ích**. Giữ chữ ký từ annotation của receiver còn nhìn thấy sau masking. |
| `receiver_unknown` | slice+candidates | không có | **Loại hợp lý**. Loại chữ ký đoán theo tên `normalize` khi `obj` chưa biết kiểu; class có trong KB không chứng minh được kiểu receiver. |
| `custom_union_alias` | slice | candidates | **Giữ bằng chứng hữu ích**. Bổ sung alias union của các class trong project không bị shadow; lưu vào KB và candidates. |
| `awaitable_alias` | slice | candidates | **Giữ bằng chứng hữu ích**. Bổ sung các dạng typing bất đồng bộ, giữ `Job = Awaitable[str]` trong candidates. |
| `explicit_alias` | slice+candidates | candidates | **Giữ bằng chứng hữu ích**. Giữ TypeAlias trong candidates; chỉ chèn vào slice nếu có dependency được xác minh. |
| `runtime_indexing_not_alias` | slice | không có | **Loại hợp lý**. `Settings = runtime[...]` là phép truy cập phần tử lúc chạy, không đủ căn cứ để khai báo type alias. |
| `literal_true_definition` | slice | slice | **Giữ bằng chứng hữu ích**. Bổ sung xử lý tĩnh nhánh module `if True/False`, không chạy code của project. |
| `runtime_conditional_definition` | slice | không có | **Loại hợp lý**. Nhánh phụ thuộc điều kiện lúc chạy có thể không định nghĩa hàm; không giả định binding luôn tồn tại. |
| `parameter_shadowing` | slice | không có | **Loại hợp lý**. Tên `convert` là tham số, không phải function cùng tên ở module. |
| `class_source_comment` | candidates | candidates | **Giữ bằng chứng hữu ích**. Giữ COMMENT tokens gắn với class/member được chọn; không lấy dấu `#` trong string làm comment. |
| `unrelated_member_comment` | candidates | không có | **Loại hợp lý**. Comment của method bị pruning cũng được loại. |
| `unrelated_target_statement` | slice | không có | **Loại hợp lý**. Loại log không tham gia dependency của target. |
| `similar_class_to_candidates` | slice+candidates | candidates | **Giữ ở candidates**. Tên tương tự chỉ giúp ranking; class `Widget` được giữ trong candidates. |
| `constructor_to_candidates` | candidates | candidates | **Giữ ở candidates**. Chữ ký constructor `uid: str` được giữ trong candidate `User`. |
| `candidate_8k_tradeoff` | candidates | không có | **Đánh đổi 8k**. Body marker bị bỏ có chủ đích theo giới hạn 8.000 ký tự: chỉ giữ signatures/docstrings khi definition quá dài. |
| `nested_lambda_contract` | không có | không có | **Giới hạn có từ bản cũ**. Chữ ký callee trong lambda lồng nhau chưa được bổ sung ở cả hai bản; ghi nhận giới hạn, không coi là đã sửa. |

## Thiếu hụt thật và phần đã sửa

Báo cáo trước sửa `remaining_context_gaps_20261013.json` ghi nhận mất bằng chứng ở external stub, alias union của class trong project, Awaitable, definition trong nhánh hằng và comment của class. Cả năm nhóm này đã có bằng chứng trở lại trong kiểm tra hiện tại. Receiver có class xác định được bổ sung chữ ký; receiver chưa biết kiểu vẫn không được gán chữ ký đoán theo tên ngắn.

Các thay đổi dùng chung catalog, binding và masking hiện có. Hai helper nhỏ tách riêng việc lấy chữ ký (`Python/signature_contracts.py`) và giữ comment nguồn (`Python/source_notes.py`); bộ nhận diện alias hiện có được mở rộng. Không thêm bộ suy luận kiểu tổng quát hoặc fallback mở rộng toàn bộ hàm.

Nhánh module chỉ được xử lý tĩnh khi điều kiện là literal boolean. Assignment trong nhánh chết bên trong function vẫn tạo local binding theo Python nên tiếp tục chặn lookup ra module. Chữ ký ngoại bộ yêu cầu explicit import và KB record duy nhất; record cũ thiếu module chỉ dùng cho root package. Receiver hỗ trợ `self`/`cls`, khởi tạo trực tiếp hoặc annotation bằng tên kiểu chưa bị mask, import trong project và kế thừa một lớp cơ sở; các binding mơ hồ hoặc động vẫn bị từ chối.

Diagnostics của chữ ký ngoại bộ ghi `provenance_kind=kb_record`: `source_file` là file JSON KB và `source_line` là số thứ tự record, không phải dòng code upstream. Chữ ký trong project ghi đúng file và dòng definition.

Comment thuộc member được chọn tính vào cùng giới hạn 8.000 ký tự. Với definition quá dài, signatures/docstrings được ưu tiên đúng quy tắc đã thống nhất; không tuyên bố toàn bộ body/comment hữu ích còn nguyên trong trường hợp này. Shared KB tiếp tục loại return annotations; chỉ bản sao của contract liên quan được đọc sau masking.

## Xác thực và cách chạy lại

- Toàn bộ bộ kiểm thử pipeline: **341 passed, 2 skipped**. Bộ mới có 42 tests, gồm danh mục bằng chứng, tính độc lập với annotation, shadowing, gán lại binding, stub trùng lặp, namespace của project, receiver kế thừa và kiểm tra phân biệt comment/string.
- Các mẫu người dùng cung cấp: **9/9**, `evidence_regressions_inventory_20261013.json`.
- Replay các file target/dependency upstream, dùng đúng revision đã pin của báo cáo trước: **9/9**, `evidence_upstream_inventory_20261013.json`. Không thực thi code upstream.
- Sinh notebooks qua generator; dry-run xác thực **19 physical jobs**, phân bố **7/6/6**, không đổi kế hoạch account và merge.
- Policy `ast-context-v7-verified-signature-evidence`, retrieval v16, project KB v7: vô hiệu hóa resume/artifacts cũ để lần build sau dùng code mới.

```powershell
python codet5p_type_retrieval/check_evidence_inventory.py --output reports/evidence_inventory_current_20261013.json
python codet5p_type_retrieval/check_evidence_regressions.py --output reports/evidence_regressions_inventory_20261013.json
python codet5p_type_retrieval/check_evidence_sources.py --manifest reports/evidence_upstream_replay_20261013.json --output reports/evidence_upstream_inventory_20261013.json
python -m pytest codet5p_type_retrieval/tests -q -p no:cacheprovider
```

Giới hạn: đây là audit theo nhóm và fixtures/replay các file đã pin, chưa quét lại toàn bộ dataset v15/v18 và chưa chạy model inference. Kết quả không chứng minh dự đoán sẽ đúng hoặc mọi trường hợp Python đã được bao phủ. Chữ ký callee trong lambda lồng nhau còn chưa được hỗ trợ; body vượt giới hạn độ dài mất nội dung có chủ đích. Chưa commit/push Git, chưa push Kaggle hoặc tái sinh dataset.
