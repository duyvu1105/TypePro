# Kế hoạch rút gọn input TypePro bằng AST

Ngày lập: 2026-10-09.

Trạng thái: kế hoạch để review; chưa triển khai code, chưa sinh lại dữ liệu và chưa chạy/push Kaggle.

## 1. Mục tiêu và phạm vi

Triển khai ba thay đổi theo yêu cầu:

1. Cắt thân target function bằng AST, giữ bằng chứng phục vụ suy luận kiểu.
2. Cắt hàm liên quan lấy từ project index theo đối số/tham số và kết quả lời gọi. Nếu không xác định chắc chắn tham số tương ứng, giữ toàn bộ hàm.
3. Với class của project trong recommendation: chọn method/thuộc tính phù hợp và giữ nguyên thân từng method được chọn. Chưa cắt câu lệnh bên trong method của class recommendation.

Giữ cấu trúc input gồm target header, interprocedural slice và recommendation. Không dùng nhãn ground truth để chọn code. Không thay đổi tập project, cách chia train/validation/test hoặc số lượng ứng viên recommendation trong giai đoạn đầu.

Chỉ tạo file kế hoạch ở bước hiện tại. Việc triển khai, tạo dataset mới, train và push là các bước riêng; không thực hiện trong lượt lập kế hoạch này.

## 2. Hiện trạng đã kiểm tra

| Điểm trong mã nguồn | Hành vi hiện tại | Thay đổi dự kiến |
| --- | --- | --- |
| `Python/slicing_code_class.py::slicing_params` | Chèn toàn bộ target function bằng `ast.unparse` | Thay bằng AST slice theo tham số |
| `Python/slicing_code_class.py::collect_func_slicing` | Chèn toàn bộ hàm cần đoán return; duyệt lời gọi toàn hàm | Slice theo return/yield, chỉ mở rộng lời gọi liên quan |
| `Python/slicing_code_class.py::slicing_var` | Thu thập các statement liên quan tới biến | Dùng chung phân tích phụ thuộc cho biến trong hàm; giữ đường xử lý global tương thích |
| `Python/project_index.py::function_source` | Hàm có annotation chỉ lưu chữ ký; hàm không annotation lưu thân | Bổ sung tra cứu AST/source đầy đủ, không phụ thuộc chuỗi biểu diễn cũ |
| `Python/function_methods.py::get_target_name_signals` | Tra theo qualified name rồi tên ngắn | Bổ sung kết quả resolve có trạng thái chắc chắn/mơ hồ |
| `Python/slicing_code_class.py::get_call_func_signatures` | Nhận tên gọi, chưa bind đối số tới tham số để cắt | Giữ call AST, caller scope và vai trò dữ liệu |
| `Python/project_kb.py::build_project_kb` | Class definition bị giới hạn 16.000 ký tự | Bổ sung nguồn cấu trúc đủ để chọn nguyên method |
| `Python/project_kb.py::target_member_query` | Có truy cập thành viên và alias đơn giản cho arg | Mở rộng truy vấn cho arg, biến, return và constructor |
| `Python/project_kb.py::top_project_types` | Rank rồi trả bản định nghĩa | Giữ ranking trước; rút gọn bản copy sau khi chọn ứng viên |
| `Python/export_slices.py` | Mask source, gọi slicer, lấy recommendation, làm sạch output | Điều phối chế độ mới, mask và diagnostics |
| `codet5p_type_retrieval/preprocess_generative.py` | Ghép input từ slice và recommendation | Giữ format; bảo toàn thông tin phiên bản trong pipeline |

Nhánh return trong `collect_func_slicing` có điều kiện `isinstance(node, ast.Return)` bên trong vòng lặp `node1`. Khi thay nhánh này phải kiểm thử việc thu thập return theo node đúng, không dựa vào hành vi hiện có.

## 3. Hợp đồng bảo toàn thông tin

- AST slice là ngữ cảnh cho mô hình, không phải chương trình đảm bảo chạy tương đương mã gốc.
- Dù vậy, mỗi hàm/class được render riêng phải parse được trước khi đổi placeholder AST thành `<mask>`.
- Giữ tên, chữ ký, default, positional-only, keyword-only, decorator và async khi chúng cần để hiểu lời gọi/kiểu.
- Không lấy return của hàm/lambda lồng nhau làm return của hàm ngoài.
- Giữ các nhánh có thể trả về kiểu khác nhau, return rỗng và đường có thể rơi xuống cuối hàm để không mất bằng chứng `None`.
- Giữ cập nhật container, thuộc tính, alias, mutation qua method và điều kiện điều khiển liên quan.
- Không sửa AST/source/KB dùng chung tại chỗ. Mỗi mẫu dùng bản copy và masking riêng.
- Không cắt theo giới hạn ký tự giữa một method. Nếu thiếu thông tin hoặc không chứng minh được việc bỏ code là phù hợp, giữ rộng hơn và ghi lý do.
- Không coi fallback toàn hàm là bảo đảm giữ đủ nếu chỉ có chữ ký từ index: phải đọc được thân hàm từ source/AST tương ứng.

## 4. Kiến trúc dự kiến

### 4.1. Module AST dùng chung

Tạo module dự kiến `Python/ast_context_slicer.py`, cung cấp:

- Tra cứu định nghĩa theo project, file, qualified name và vị trí source.
- Phân tích đọc/ghi tên, thuộc tính, subscript, alias và mutation.
- Chọn statement theo tiêu chí đầu vào hoặc đầu ra.
- Resolve callee và bind arguments mà không import/chạy code project.
- Render bản copy AST theo thứ tự source, chèn `pass` khi cấu trúc yêu cầu và marker cho phần đã bỏ.
- Kết quả gồm node/code, chế độ `sliced`/`full_fallback`, lý do, số statement trước/sau và định danh nguồn.

Tên API cụ thể chốt khi triển khai; tránh thêm một tầng string parsing cho các chuỗi `function ...` không phải Python.

### 4.2. Index và cache

Giữ interface index cũ cho các nơi đang sử dụng. Thêm lookup sidecar theo `(file, qualified_name, lineno)` hoặc cấu trúc tương đương để lấy chữ ký AST, decorator, source span và thân đầy đủ.

- Tận dụng `parsed_files`/project scan hiện có; không parse lại toàn project cho mỗi mẫu.
- Không ghi thêm toàn bộ thân hàm trùng lặp vào từng row dữ liệu.
- Định nghĩa được đọc dưới source overlay đã mask phải thay thế AST cache cũ của file mục tiêu.
- Cache kết quả phụ thuộc tiêu chí slice, vị trí call và trạng thái mask; không chỉ khóa bằng tên hàm hoặc tham số.
- Dùng cache hữu hạn cho kết quả theo mẫu; AST dùng chung chỉ đọc.

## 5. Cắt target function

### 5.1. Mục tiêu là tham số

1. Xác định đúng function/method và đúng tham số theo AST sau masking.
2. Lấy seed là các lần dùng tham số, alias của nó và thao tác lên thuộc tính/container bắt nguồn từ nó.
3. Theo luồng dữ liệu tiến để giữ biến trung gian và nơi sử dụng liên quan.
4. Theo luồng dữ liệu ngược để giữ giá trị khác cần hiểu những câu lệnh đã chọn.
5. Giữ khối điều khiển bao quanh, điều kiện thu hẹp kiểu, nhánh guard/early exit liên quan và các lệnh điều khiển cần thiết.
6. Giữ chữ ký target; không thêm lại nguyên thân qua một đường lấy definition khác.

### 5.2. Mục tiêu là kiểu trả về

1. Lấy seed là mọi `return`/`yield`/`yield from` trực thuộc hàm.
2. Lần ngược biểu thức trả về qua phép gán, alias, unpack, mutation container/thuộc tính và lời gọi.
3. Giữ điều kiện quyết định các nhánh trả về, kể cả nhánh không trả giá trị.
4. Xử lý `try/except/finally`, loop, context manager và async một cách bảo thủ; giữ nguyên khối khi chưa phân tích chắc chắn.
5. Chỉ truy hồi callee có liên quan tới phần được giữ.

### 5.3. Mục tiêu là biến trong hàm

Dùng phép gán mục tiêu và các lần sử dụng làm seed. Giữ khai báo/masking đúng vị trí, nguồn tạo giá trị, biến trung gian và ngữ cảnh điều khiển. Không biến yêu cầu này thành việc cắt mọi function không liên quan trong file.

### 5.4. Thuật toán ban đầu

Xây bảng dependency cấp statement, theo phạm vi; duyệt tới fixed point. Phân biệt định nghĩa lại tên với alias còn hiệu lực. Với nhánh/loop, hợp các trạng thái có thể xảy ra; nếu chưa phân biệt được thì giữ tất cả definition có thể tới điểm dùng. Không dùng quy tắc “chỉ giữ dòng có tên biến”.

Các hiệu ứng động như `exec`, `eval`, reflective attribute, closure không resolve được hoặc side effect có thể ảnh hưởng mục tiêu dẫn tới giữ nguyên khối/hàm với reason. Không loại logging hay call chỉ dựa vào tên hàm.

## 6. Cắt hàm liên quan từ project index

### 6.1. Resolve đúng callee trước

Ưu tiên tên đầy đủ, import/alias tường minh, scope lexical và receiver xác định chắc chắn. Tên ngắn đơn lẻ chỉ là tập ứng viên, không tự động được xem là resolve chắc chắn.

Không suy đoán kiểu receiver từ nhãn cần dự đoán hoặc tên class có vẻ giống tên biến. Với method có dispatch động/khả năng override chưa loại trừ, đánh dấu mơ hồ.

### 6.2. Bind đối số tới tham số

Bind bằng mô hình chữ ký AST, không thực thi code:

| Trường hợp | Chính sách |
| --- | --- |
| Positional, keyword, hỗn hợp | Bind theo đúng chữ ký; không yêu cầu cú pháp `param=value` |
| Default, `/`, keyword-only `*` | Giữ đúng quy tắc Python và default có liên quan |
| Bound method, classmethod, staticmethod | Bù receiver theo loại descriptor khi xác định chắc chắn |
| Tuple/list literal trong `*args`, dict literal trong `**kwargs` | Chỉ mở rộng khi biết chắc nội dung, thứ tự và không có key trùng/ghi đè mơ hồ |
| `*values`, `**options` chưa biết | Full-function fallback |
| `*args`/`**kwargs` của callee | Chỉ cắt khi xác định được đường dùng tương ứng; nếu chưa hỗ trợ thì fallback |
| Decorator thay chữ ký, `partial`, callable object, alias động | Chỉ cắt khi có resolve/bind chắc chắn; giai đoạn đầu fallback |
| Binding không hợp lệ | Giữ lời gọi và định nghĩa hiện có; ghi `invalid_binding`, không tự sửa lời gọi |

### 6.3. Tiêu chí cắt callee

- Đối số mang dữ liệu mục tiêu: slice theo tham số nhận đối số đó.
- Giá trị lời gọi tạo dữ liệu mục tiêu: slice theo return/yield của callee.
- Cả hai vai trò xuất hiện: hợp hai slice.
- Nhiều lời gọi cùng một hàm: hợp tiêu chí theo đúng định danh hàm, không giữ nhiều bản gần giống nhau.
- Callee đọc global/closure: giữ dependency resolve được; nếu ảnh hưởng không rõ thì fallback.
- Giới hạn mở rộng liên hàm ban đầu một hop; không mở rộng đệ quy không giới hạn. Hàm đệ quy có cycle detection và giữ ngữ cảnh bảo thủ.

### 6.4. Fallback bắt buộc

- Callee đúng nhưng param không chắc chắn: toàn bộ thân callee.
- Callee mơ hồ: giữ toàn bộ các ứng viên mà index hiện tìm được, ghi rõ mơ hồ; không chọn một ứng viên tùy ý.
- Không có source/parse thất bại: giữ representation hiện có và báo `source_unavailable`/`parse_error`; không gọi đó là full-function fallback thành công.
- Chỉ có API thư viện ngoài: giữ chữ ký/định nghĩa hiện có; không thực thi thư viện để introspect.
- Toàn hàm fallback vẫn phải qua masking cuối cùng. Không âm thầm thay fallback bằng chữ ký để giảm token.

## 7. Chọn thành viên class recommendation

### 7.1. Nguồn dữ liệu và ranking

Giữ một KB/project và nguyên tắc xây KB không dùng return annotation làm nguồn truy hồi. Không tạo KB riêng theo target.

Ranking ứng viên vẫn diễn ra trước trên dữ liệu được mask đúng chính sách; sau đó tạo bản copy định nghĩa rút gọn. Đo riêng tác động ranking do slice mới thay đổi, không tuyên bố danh sách ứng viên chắc chắn giữ nguyên.

Chuỗi definition hiện bị cắt ở 16.000 ký tự có thể không parse được. Bổ sung bản cấu trúc/source đầy đủ hoặc member source spans trong KB có version để chọn nguyên method. Không bỏ giới hạn chuỗi mà không đánh giá kích thước KB. Giải pháp phải dùng được khi chỉ có project KB đã đóng gói, không phụ thuộc repo còn trên máy lúc preprocess.

### 7.2. Truy vấn thành viên

- Lấy member access từ code đã mask, theo đúng receiver/alias và scope.
- Không gán `.text` trong `client.fetch().text` thành thuộc tính của `client`; đó là thuộc tính kết quả lời gọi.
- Constructor của class được gọi trực tiếp là tín hiệu giữ `__new__`/`__init__` thích hợp.
- Bổ sung protocol rõ ràng: subscript, iteration, context manager, async iteration khi xác định được receiver.
- Với return/biến: nối truy cập ở nơi dùng và constructor trong slice; nếu chưa xác định được thì fallback.

### 7.3. Quy tắc giữ code

1. Giữ tên class, bases, keywords và decorator của class.
2. Giữ nguyên thân, chữ ký và decorator của các method được chọn, gồm cả `__init__` nếu được chọn. Không cắt câu lệnh trong method ở giai đoạn này.
3. Giữ thuộc tính cấp class liên quan, annotation/default và property getter/setter/deleter tương ứng.
4. Giữ method thiết lập thuộc tính liên quan, ví dụ `__init__` gán `self.transport`; toàn bộ method đó được giữ.
5. Mở rộng theo dependency giữa các thành viên: `self._helper()`, `cls.factory`, class constant, property và member lồng nhau resolve được.
6. Theo dependency tới fixed point trong class; nếu vòng lặp dependency thì giữ các thành viên trong vòng, không lặp vô hạn.
7. Thành viên kế thừa: dùng định danh lớp cha chắc chắn, giữ đoạn lớp cha cần thiết với provenance. MRO/đa kế thừa mơ hồ thì giữ rộng và ghi reason.
8. Không có member khớp, truy cập động, decorator sinh member hoặc dependency chưa chắc: giữ definition class đầy đủ khả dụng; không trả một class rỗng gây hiểu lầm.
9. Chỉ áp dụng cho `source=project`, `kind=class`; imported/API/type alias dùng đường hiện tại.
10. Chèn `# omitted unrelated members` khi đã bỏ thành viên.

## 8. Masking, trùng lặp và ngân sách

- Mask source trước retrieval và mask bản definition trả về sau khi render, kể cả full fallback và bản lớp cha.
- Phép kiểm tra leakage phải bao phủ cả target body, callee, class method, chữ ký và metadata. Không đưa nhãn vào diagnostics.
- Không mutate KB theo mẫu; chạy hai mẫu khác nhau trên cùng KB phải cho kết quả độc lập thứ tự.
- Loại trùng theo qualified identity/file/source span. Không loại hai class trùng tên từ module khác.
- Có thể bỏ class summary trong slice khi recommendation chứa cùng class và bảo toàn thông tin summary tương ứng; nếu không chứng minh được thì giữ.
- Giữ chữ ký/marker và code sử dụng class trong slice.
- Giai đoạn này rút gọn theo ngữ nghĩa, chưa thay đổi chính sách token truncation của train/inference. Báo rõ tỷ lệ fallback còn vượt context; không tuyên bố fallback luôn đến được mô hình đầy đủ.

## 9. Phiên bản dữ liệu và diagnostics

Thêm phiên bản chính sách, dự kiến `ast-context-v1`, vào runtime manifest, project status và raw row phù hợp. Rà soát version/schema hiện có trước khi chọn số mới; không tự giả định số tiếp theo.

- Cache resume phải so cả retrieval schema và context policy; không tái dùng raw slice hoàn tất từ chính sách cũ.
- Merge/verify từ chối trộn các chính sách không tương thích.
- Cho phép chế độ baseline đầy đủ để đối chiếu; tách output/cache giữa baseline và bản cắt.
- Diagnostics ngoài prompt: số statement/ký tự trước-sau theo thành phần, kept members, callee identity, binding status, fallback reason, thời gian và cache hit.
- Reasons tối thiểu: `ambiguous_callee`, `unresolved_argument_binding`, `dynamic_member_access`, `unsupported_effect`, `source_unavailable`, `parse_error`, `no_relevant_members`.

## 10. Thứ tự triển khai và file dự kiến

| Bước | Công việc | File dự kiến |
| --- | --- | --- |
| 1 | Bổ sung source/AST lookup và identity, không đổi output baseline | `Python/project_index.py`, `Python/function_methods.py` |
| 2 | Bộ phân tích dependency, render và fallback dùng chung | Module mới `Python/ast_context_slicer.py` |
| 3 | Cắt target arg/return/biến và nối call context | `Python/slicing_code_class.py`, `Python/export_slices.py` |
| 4 | Resolve/bind và cắt hàm liên quan; giữ full source khi fallback | Các file bước 1–3 |
| 5 | Nguồn class có cấu trúc, chọn member và giữ nguyên method body | `Python/project_kb.py`, module AST, export |
| 6 | Diagnostics, context version, resume/merge guard | `prepare_dataset.py`, `merge_shards.py`, `verify_dataset.py` và các nơi quản lý manifest thực tế |
| 7 | Kiểm thử tích hợp, đo baseline/bản cắt, cập nhật tài liệu | `codet5p_type_retrieval/tests`, `reports` |

Nếu cần truyền option mới qua Kaggle, đọc lại README và account plan hiện hành, sửa generator rồi sinh artifacts; không sửa notebook bằng tay. Bảo toàn workflow 19 physical jobs, mapping 7/6/6 và các partition hiện có. Không push trong quá trình triển khai local nếu chưa có yêu cầu chạy thật.

## 11. Ma trận kiểm thử

### 11.1. Target slice

- Loại statement độc lập nhưng giữ alias chain, shadow/reassignment và dependency hai chiều.
- Container mutation, augmented assignment, destructuring, thuộc tính và side effect chưa resolve.
- Nhiều return khác kiểu, implicit None, return rỗng, generator, async/await.
- Guard, loop, break/continue, try/except/finally, with và match nếu interpreter hỗ trợ.
- Nested function/lambda/class không làm lẫn scope và return.
- Code không phân tích được chuyển fallback có reason.

### 11.2. Binding và callee

- Positional, keyword đảo thứ tự, mixed, defaults, `/`, keyword-only.
- Bound/unbound method, classmethod, staticmethod và decorator mơ hồ.
- Literal `*`/`**` biết rõ; unpack động; variadic và argument bị truyền trùng.
- Import alias, same-name function ở hai module, override và unknown receiver.
- Return slicing khi chưa biết param: tuân thủ full fallback nếu call binding cần thiết vẫn mơ hồ.
- Nhiều call sites hợp slice; recursion không mở rộng vô hạn.
- Hàm annotated vẫn lấy được nguyên thân khi fallback.

### 11.3. Class recommendation

- Giữ nguyên toàn bộ body method được chọn; loại method độc lập.
- Dependency helper/attribute/constructor, property và protocol methods.
- Alias, result-member chain, kế thừa/đa kế thừa và dynamic access.
- Class dài hơn 16.000 ký tự vẫn lấy nguyên method cuối class.
- Class trùng tên khác module không bị gộp; imported/type alias không bị đổi sai.
- Không tìm member phù hợp thì giữ class khả dụng với reason.

### 11.4. Pipeline và leakage

- Mask annotation trước và sau render; target xuất hiện lại trong callee/class fallback vẫn không lộ.
- Shared KB không bị thay đổi; thứ tự mẫu không ảnh hưởng output.
- Thay nhãn ground truth không làm thay đổi phần code được chọn.
- Raw row/input format vẫn hợp lệ; resume không reuse sai policy; merge reject mixed policy.
- Test baseline regression hiện có, kể cả optimization/cache và fixed project split.

Chạy nhóm test mới và test liên quan trước, sau đó toàn bộ suite:

```powershell
python -m pytest codet5p_type_retrieval/tests -q -p no:cacheprovider
```

Không cần chạy lại full suite nhiều lần nếu không có thay đổi/failure mới. Phải hoàn thành full suite trước Git/Kaggle push theo runbook.

## 12. Đánh giá và điều kiện hoàn tất

So sánh baseline và bản cắt trên cùng project revision, sample IDs, nhãn, split và tokenizer. Bao gồm mẫu ngắn, dài, nhiều nhánh, fallback và class dài.

Đo theo từng thành phần: ký tự/token trước-sau, p50/p90/p95, tỷ lệ vượt context, tỷ lệ fallback theo reason, thời gian/mẫu và bộ nhớ. Đối chiếu số lượng mẫu để tránh kết quả đẹp do vô tình bỏ mẫu khó.

Review các cặp code trước/sau và kiểm thử các bằng chứng quyết định kiểu. Đánh giá accuracy cần chạy mô hình riêng; trước khi có kết quả chỉ kết luận về việc giữ code và giảm token. So sánh checkpoint hiện có trên hai input chỉ là ablation ban đầu; muốn kết luận cho pipeline mới cần train/eval cùng chính sách.

Điều kiện nghiệm thu triển khai:

- Ba phạm vi cắt hoạt động theo chính sách trên và có baseline đối chiếu.
- Param không chắc chắn dẫn tới full-function fallback có source đầy đủ nếu có thể lấy được.
- Class recommendation chỉ chọn thành viên, không cắt thân method được chọn.
- Masking, shared KB, cache version và merge guard được kiểm thử.
- Full test suite đạt; báo cáo số liệu giảm input, fallback và giới hạn còn lại.
- Không công bố độ chính xác được bảo toàn nếu chưa có đánh giá mô hình.

## 13. Giới hạn được chấp nhận trong phiên bản đầu

Không cố giải quyết toàn bộ dispatch động, reflection, monkey patch, decorator hay tác dụng phụ của Python. Không chạy code project để resolve. Phân tích chưa chắc chắn dẫn tới giữ rộng hơn; giảm token sẽ không đồng đều giữa các mẫu. Đây là tradeoff có chủ ý để tránh cắt mất bằng chứng chỉ vì muốn input ngắn.
