# Kế hoạch sửa input phình và xử lý lại dữ liệu TypePro

Ngày lập: 2026-10-10 (Asia/Saigon).

**Trạng thái: bản kế hoạch để người dùng review. Lượt này chỉ viết tài liệu; không sửa code, commit/push, chạy shard, merge, publish hoặc train. Chưa được phép triển khai phương án này.**

Kế hoạch này thay thế những phần chưa đúng của `ke_hoach_rut_gon_input_ast.md`: fallback khi chưa resolve callee, definition candidate chưa có trần 16.000 ký tự và kiểm chứng độ dài input.

## 1. Sửa gì, nói ngắn gọn

1. Tên hàm trùng nhau được dùng để xét ứng viên, không phải lý do chèn mọi thân hàm vào slice.
2. Chỉ đưa code hàm liên quan vào slice sau khi xác định được đúng hàm. Biết đúng hàm nhưng chưa bind chắc param mới giữ nguyên hàm đó.
3. KB lưu class đầy đủ. Definition đưa vào từng candidate được giới hạn tối đa 16.000 ký tự như trước, sau bước chọn member/masking; không cắt bản trong KB.
4. Kiểm tra khả năng tận dụng 19 Dataset hiện có trước khi quyết định xử lý lại bao nhiêu dữ liệu. Không mặc định chạy lại 19 job tạo shard.
5. Đo trước–sau và cho người dùng xem kết quả trước khi triển khai Kaggle.

## 2. Nguyên nhân đã xác định trong code

So sánh commit trước AST `83fc661` với commit AST `9610ee4`:

| Phần | Trước | Sau thay đổi AST | Vấn đề cần sửa |
| --- | --- | --- | --- |
| Class trong KB/recommendation | Definition bị cắt ở 16.000 ký tự | KB lưu đầy đủ; reducer không chắc thì trả nguyên class | Bỏ ngưỡng nhưng chưa có giới hạn cho bản đưa vào prompt |
| Hàm có annotation trong project index | Thường chỉ có chữ ký | Catalog AST có toàn bộ thân | Nhầm việc có source đầy đủ với việc được phép chèn source vào slice |
| Fallback theo tên ngắn | Đã có trong `get_target_name_signals` | Được giữ lại và xuất hiện thêm trong catalog/slicer | Khi callee chưa rõ vẫn chèn mọi hàm khớp tên |

Các điểm phải rà và sửa đồng bộ:

- `Python/function_methods.py::get_target_name_signals`.
- `Python/ast_context_slicer.py::FunctionCatalog.lookup`.
- `Python/slicing_code_class.py::get_call_func_names` và `get_call_func_signatures`.
- Các nhánh target arg/return/var, nơi thu thập caller/callee và nối code vào slice.
- `Python/project_kb.py::top_project_types` và `reduce_class`.
- `Python/export_slices.py` và `codet5p_type_retrieval/preprocess_generative.py`, nơi tạo dữ liệu và ghép input cuối.

Hai mẫu bắt buộc kiểm tra lại theo số liệu người dùng cung cấp, chưa coi là số liệu đã đo lại trong lượt lập kế hoạch:

- `_get_partition_data` / `SqlBaseParser`: class từ 16.000 lên 430.474 ký tự; input từ 14.184 lên 110.342 token.
- `labd/commercetools-python-sdk`, `HttpAdapter.match`: input khoảng 1,30 triệu ký tự / 270.333 token, slice chứa 2.319 định nghĩa `deserialize` và 2.316 định nghĩa `serialize`.

## 3. Phân biệt candidate với code trong slice

Trong tài liệu này, “candidate” là ứng viên còn phải xét. “Hàm liên quan trong slice” là định nghĩa đã được chứng minh là đích của lời gọi.

Danh sách hàm khớp tên dùng nội bộ để resolve không đồng nghĩa với `recommendation_types`: trường này hiện chứa ứng viên kiểu/class. Không tự đưa hàng nghìn hàm khớp tên thành hàng nghìn recommendation mới.

| Kết quả tra cứu lời gọi | Xử lý slice | Xử lý ứng viên |
| --- | --- | --- |
| Xác định đúng hàm, bind được đối số | Lấy AST slice theo param/kết quả liên quan | Giữ cơ chế recommendation riêng |
| Xác định đúng hàm, bind không chắc, ví dụ `*args` chưa rõ | Giữ nguyên đúng hàm đó, không mở rộng sang các hàm trùng tên | Ghi lý do fallback |
| Chưa xác định đúng hàm/receiver | Giữ lời gọi tại vị trí vốn có trong target slice; không chèn thân các hàm đoán theo tên | Có thể giữ bằng chứng tên/member để xét ứng viên theo cơ chế hiện có |
| Không tìm thấy source của hàm đã resolve | Giữ lời gọi và chữ ký nếu có; ghi source thiếu | Không thay thế bằng hàm trùng tên ở nơi khác |

Không tự biến hàm có annotation thành full-body context. Annotation không quyết định một hàm có liên quan hay không. Source đầy đủ chỉ là tài nguyên để slice sau khi resolve đúng.

### 3.1. Resolve bằng bằng chứng nào

- Plain call `f(x)`: scope từ vựng, module hiện tại và import/alias rõ ràng.
- `module.f(x)`: import module/alias và đường dẫn module xác định được.
- `self.f(x)` / `cls.f(x)`: class bao quanh; lớp cha chỉ khi xác định được phương thức và không có yếu tố động làm kết quả mơ hồ.
- `obj.f(x)`: chỉ dùng nguồn gốc receiver chứng minh được từ code, ví dụ phép gán constructor không bị ghi đè trên các đường đi liên quan.
- Decorator, descriptor, monkey-patch, import động, shadowing, nhiều nhánh gán hoặc kế thừa mơ hồ: đánh dấu chưa resolve; không đoán để lấy thân hàm.
- Một hàm duy nhất trùng tên trong toàn project cũng chưa đủ chứng minh đó là callee của receiver chưa rõ.

Không dùng kiểu đang cần dự đoán hoặc nhãn `gttype` để xác định receiver. Nếu target chính là `obj`, không giả định `obj` thuộc một class ứng viên rồi dùng giả định đó làm bằng chứng cho chính kiểu của `obj`.

### 3.2. Đổi hợp đồng giữa resolver và slicer

Resolver trả kết quả có cấu trúc: `resolved` / `ambiguous` / `unresolved`, định danh source gồm file + qualified name + vị trí, bằng chứng resolve và lý do chưa chắc.

Slicer chỉ nhận định nghĩa full-body từ nhánh `resolved`. Không để nhánh trả chuỗi code dùng chung vừa phục vụ danh sách khớp tên vừa phục vụ mở rộng slice. Mọi caller của các API cũ phải được rà; không sửa một nhánh rồi còn đường fallback khác vượt qua kiểm tra.

Các index theo tên vẫn có thể dùng để tìm ứng viên nội bộ. Việc deduplicate dựa trên định danh source, không dựa riêng tên ngắn hoặc chuỗi code giống nhau. Khi số lượng ứng viên quá lớn, dùng index/count và diagnostics, không render tất cả thân hàm vào bộ nhớ/prompt.

## 4. Target function và hàm liên quan

- Giữ AST reduction của target theo bằng chứng suy luận kiểu; compound statement và tác động chưa phân tích được tiếp tục được xử lý bảo thủ.
- Chỉ mở rộng những lời gọi nằm trong phần target còn lại, một hop trong giai đoạn này.
- Tham số positional, keyword, positional-only, keyword-only, default, `*args`, `**kwargs` và bound method phải có test riêng.
- Chưa chứng minh được cách bind receiver/đối số thì không slice theo một param đoán; nếu callee đã resolve chắc thì giữ nguyên hàm đó.
- Target hoặc hàm đã resolve vẫn có thể rất dài. Ghi nhận và báo riêng, không cắt chữ tùy tiện hoặc âm thầm bỏ mẫu để làm đẹp thống kê.

## 5. Giới hạn candidate khi tạo shard

### 5.1. Hợp đồng đã chốt theo yêu cầu người dùng

**Mỗi trường `definition` đưa vào candidate/recommendation có tối đa 16.000 ký tự như trước. KB vẫn lưu đầy đủ definition, không cắt ở 16.000 ký tự.**

Đơn vị là ký tự Unicode của chuỗi Python (`len(definition)`), không phải byte hay token. Không chạy tokenizer/model trong bước tạo shard.

| Phần dữ liệu | Giới hạn |
| --- | --- |
| Definition gốc trong project KB | Lưu đầy đủ, không áp trần 16.000 |
| `recommendation_types[i].definition` trong raw output | Tối đa 16.000 ký tự cho từng candidate |
| `recommendation_types[i].definition` trong final output | Tối đa 16.000 ký tự, kiểm tra lại trước ghép input |
| Tên/type, qualified name, metadata, tag và separator | Không tính vào 16.000 ký tự của `definition` |
| Số recommendation | Tối đa 10 như hiện tại |
| Tổng section recommendation | Không thêm ngân sách tổng riêng trong thay đổi này |

Bỏ đề xuất ngân sách tổng 32.000 ký tự và summary riêng 2.000 ký tự ở bản plan trước. Không chia lại ngân sách giữa các candidate theo ranking và không tự đổi candidate sang summary vì ngân sách tổng.

Cấu hình dùng chung dự kiến là `candidate_definition_max_chars=16000`, lưu vào manifest/policy và truyền đồng bộ qua exporter, reprocess và preprocess. Không hard-code các giá trị khác nhau ở từng bước.

### 5.2. Thứ tự xử lý definition của candidate

1. Đọc definition đầy đủ từ KB; làm việc trên bản copy và mask target theo hợp đồng chống leak.
2. Với class của project, dùng AST chọn method/thuộc tính liên quan và các phụ thuộc constructor/helper cần thiết. Ở bước lựa chọn này giữ nguyên thân method được chọn.
3. Nếu không chọn chắc được member, có thể dùng bản definition đầy đủ đã mask làm fallback của candidate; đây không phải quyền đưa class/hàm chưa resolve vào slice.
4. Sau khi có chuỗi definition để đưa vào candidate, áp dụng trần cuối cùng giống trước: `candidate_definition = rendered_definition[:16000]`.
5. Lưu bản đã giới hạn vào `recommendation_types[i].definition`, rồi mới ghép vào input. Không gắn thêm marker vào chính definition làm nó vượt 16.000 ký tự.
6. Ghi diagnostics riêng: độ dài definition gốc, độ dài sau chọn member, độ dài cuối, có bị cắt hay không và lý do fallback.
7. Không ghi ngược definition đã cắt vào KB; không sửa record/AST dùng chung tại chỗ.

Ví dụ: KB chứa class dài 430.474 ký tự. Nếu chọn member thu được 9.000 ký tự thì candidate giữ 9.000. Nếu vẫn dài 25.000 hoặc fallback cả class thì candidate chỉ giữ 16.000 ký tự đầu của bản được render; KB vẫn giữ đầy đủ.

**Hệ quả của việc khôi phục cách cắt cũ:** phép cắt chuỗi có thể kết thúc giữa method hoặc statement. Yêu cầu giữ nguyên thân method áp dụng trước bước giới hạn; trần 16.000 của definition đưa vào candidate là yêu cầu cuối cùng được ưu tiên. Không tuyên bố definition sau cắt luôn parse được hay là source hoàn chỉnh. Chưa tự thay cách cắt cũ bằng summary/signature trong đợt này.

### 5.3. Phạm vi áp dụng và kiểm tra

- Giới hạn mọi definition thực sự đi vào candidate, không chỉ class lớn hoặc một nguồn recommendation riêng.
- Giữ nguyên danh sách ứng viên, định danh và thứ tự ranking qua bước giới hạn; chỉ đổi chuỗi definition và diagnostics. Không bỏ candidate hoặc chọn theo gold để đạt trần.
- Áp dụng ở exporter/reprocess để raw output đã được giới hạn. Preprocess dùng cùng policy như lớp bảo vệ cuối, bảo đảm không có nhánh ghép definition chưa giới hạn vào input.
- Với dữ liệu cũ có definition quá dài, tạo bản output mới đã giới hạn; không coi thao tác giới hạn definition là đã sửa xong lỗi hàm trùng tên trong slice.
- Trần này chỉ áp dụng cho candidate definition; không cắt KB, target slice hoặc hàm liên quan đã resolve bằng `[:16000]`.
- Tối đa 10 candidate có thể chứa tới 160.000 ký tự definition, chưa tính slice và định dạng. Không hứa toàn input vừa context model; đo ký tự/token toàn input riêng trong báo cáo.

Việc thay đổi danh sách/ranking do slice mới cung cấp bằng chứng khác phải được thống kê riêng. Không cam kết ranking toàn pipeline bất biến khi sửa nguồn slice.

## 6. Masking và chống leak

- Mask target trước khi resolve, chọn member, slice, rank và render prompt.
- Không đọc nhãn target để chọn callee, member hoặc nội dung definition candidate.
- Không dùng return annotation làm nguồn kiểu cho KB/resolver; giữ hợp đồng hiện tại về shared KB.
- Không đưa nhãn thiếu vào recommendation để nâng coverage.
- Không sửa KB/AST chia sẻ tại chỗ; dùng bản copy theo mẫu.
- Test thay đổi annotation target nhưng giữ code và KB cố định: slice, candidate selection và prompt phải bất biến ngoài nhãn được lưu riêng.
- Tên/member giống nhau chỉ tạo bằng chứng ứng viên, không biến thành khẳng định receiver thuộc class đó.

## 7. Tận dụng dữ liệu đã có: không mặc định chạy lại 19 shard

### 7.1. Bước kiểm kê trước khi quyết định cách chạy

Đọc manifest và file listing của đúng 19 đầu vào trong `shard_merge_plan.json`, ghi version cụ thể. Xác nhận có `raw_slices`, metadata, project status, project KB và revision lock tương thích. Xác nhận metadata nào cho phép tìm lại target theo project, file, class/function, dòng và scope.

Không dùng final JSONL làm nguồn duy nhất: nó có thể thiếu thông tin source/provenance cần để sửa đúng slice.

**Đính chính lời khẳng định trước:** `raw_slices` hiện lưu slice đã ghép thành chuỗi; shared KB không lưu đầy đủ AST/source của mọi hàm. Có dữ liệu này chưa chứng minh có thể dựng lại slice đúng hoàn toàn offline. AST target đã cắt có thể mất statement; tên hàm trùng nhau cũng không đủ để xác định khối source thuộc về ai.

### 7.2. Chọn đường xử lý theo dữ liệu thực có

| Trường hợp | Cách làm |
| --- | --- |
| Chỉ cần render lại class recommendation; KB và metadata đủ | Render lại từ KB có sẵn, không rebuild KB và không clone project |
| Sửa slice, có source/AST đúng revision và định danh đủ | Re-export context cho các sample cần xử lý; tái dùng KB/metadata |
| Sửa slice, không có source đủ trong artifacts | Lấy lại source đúng commit theo revision lock của project liên quan; tái dùng KB nếu schema tương thích; không checkout HEAD tùy ý |
| Không đủ provenance để biết sample nào an toàn tái dùng | Xử lý lại context của toàn bộ tập sample bị ảnh hưởng bởi policy, báo rõ quy mô; không chỉ sửa hai outlier rồi tuyên bố hết lỗi |
| Không khôi phục được source/target đúng revision | Ghi danh sách blocked/missing và nguyên nhân; không tự sinh dữ liệu thay thế hoặc âm thầm drop |

Không xóa các `def serialize`/`def deserialize` bằng regex trên slice đã ghép. Cách đó có thể xóa hàm đúng và vẫn không khôi phục các statement cần thiết.

Trước khi triển khai, phải báo số project/sample cần lấy lại source, số chỉ cần render và chi phí dự kiến. “Xử lý lại context” có thể vẫn phải đi qua nhiều project, nhưng khác với chạy lại toàn pipeline clone/build KB/export/publish của 19 shard.

### 7.3. Output của đợt xử lý lại

- Ghi vào thư mục/payload mới, giữ nguyên 19 Dataset nguồn và version đã chụp.
- Có ledger resume theo project/sample; lưu hash đầu vào, source revision, code commit, policy và kết quả kiểm tra.
- Không tái sử dụng raw output policy cũ như thể đã xử lý policy mới.
- Dự kiến policy mới `ast-context-v2-resolved-callees-bounded-candidates`; tên schema/stamp cuối cùng chốt khi triển khai và cập nhật đồng bộ exporter, preprocess, merge và validator.
- KB đầy đủ vẫn có thể tái dùng nếu schema tương thích; không buộc rebuild KB chỉ vì đổi cách render context.
- Giữ project split map, tập test 100 project, sample identity và label. Nếu có chênh lệch count/coverage phải giải thích trước publish; không dùng target label để điều chỉnh selection.

## 8. Kiểm thử và báo cáo trước–sau

### 8.1. Regression test về resolve và slice

- Nhiều class/module cùng có `serialize`/`deserialize`: receiver chưa rõ không làm bất kỳ thân hàm đoán nào vào slice.
- Hàm có annotation khớp tên nhưng không phải callee: không được chèn full-body.
- `self`/`cls`, import alias, plain function, scope shadowing, constructor assignment và receiver bị gán lại.
- Nhiều nhánh receiver, inheritance/descriptor/decorator động: unresolved có diagnostics.
- Callee đúng nhưng param không bind được: giữ nguyên đúng một định nghĩa đó.
- Callee/param đều chắc: AST slice giữ bằng chứng liên quan, không kéo hàm trùng tên khác.
- Rà cả target arg/return/var và các nhánh caller context để không sót đường chèn code theo tên ngắn.

### 8.2. Regression test về candidate

- Class rất dài, class sinh tự động, class không tìm được member phù hợp.
- Method liên quan nằm sau mốc 16.000 ký tự trong KB: vẫn tìm được, không cắt KB gốc.
- Method body, chữ ký, default literal hoặc dependency closure vượt 16.000 ký tự: definition cuối vẫn tuân thủ phép cắt đã chốt.
- Mỗi definition thỏa `len(definition) <= 16000`; kiểm tra các mốc 15.999, 16.000 và 16.001, cả Unicode. Tên/tag không tính vào trần; không áp ngân sách tổng riêng.
- Body còn nguyên sau bước chọn AST trước cắt; sau cắt không bắt buộc parse được. Diagnostics ghi đúng việc cắt và KB gốc không đổi.
- Ranking và danh sách trước/sau bước giới hạn render giữ nguyên; không dùng gold để ưu tiên.
- KB/AST chia sẻ không đổi sau nhiều mẫu có masking khác nhau.

### 8.3. Đo dữ liệu thực tế

Làm preview trên hai mẫu đã nêu, sau đó nhóm mẫu dài nhất, rồi audit toàn bộ output được xử lý lại.

Báo cáo cho mỗi split:

- Tổng sample, missing/failed, project coverage, sample ID và label bị thay đổi nếu có.
- Ký tự của target, related definitions, recommendation và toàn input: median, p95, p99, maximum.
- Số định nghĩa liên quan, số callee chưa resolve, số fallback full-function và số candidate bị cắt definition tại trần 16.000 ký tự.
- Số mẫu tăng/giảm độ dài; giải thích các trường hợp tăng lớn, không chỉ báo trung bình.
- Nội dung trước/sau của hai mẫu outlier và mẫu kiểm tra thủ công về bằng chứng suy luận kiểu.

Sau khi có preview, có thể audit token bằng đúng tokenizer của model train đã chọn. Đây là bước đo riêng, không phải điều kiện chạy tokenizer trong từng shard. Ghi rõ tokenizer/revision, chat template và input/label length của lệnh train thực tế; không suy cấu hình runtime từ default script hoặc notebook khác.

`42955` của một prompt không phải maximum của Dataset. Báo maximum chỉ sau khi quét đầy đủ tập được thống kê.

### 8.4. Điều kiện đạt trước triển khai

1. Mọi full-body hàm liên quan trong slice đều có provenance và bằng chứng resolve; không còn fallback chèn code toàn project theo tên ngắn.
2. Mọi candidate definition tuân thủ trần 16.000 ký tự, kể cả nhánh fallback class đầy đủ; KB gốc vẫn đầy đủ.
3. Hai outlier hết hiện tượng hàng nghìn hàm trùng tên/nguyên parser vượt trần; không thay bằng lỗi mất target.
4. Test masking/leak, binding và dependency đạt; mọi chênh lệch sample/split/coverage đều được giải thích.
5. Báo cáo toàn bộ phân bố độ dài; không tuyên bố mọi mẫu đều ngắn hơn hoặc mọi input đều vừa model khi chưa đo.
6. Full pipeline test suite đạt trước Git/Kaggle push:

   ```powershell
   python -m pytest codet5p_type_retrieval/tests -q -p no:cacheprovider
   ```

7. Người dùng được xem preview, số liệu và phương án chạy cụ thể trước khi cho phép triển khai.

## 9. File dự kiến thay đổi khi được phép code

| File/nhóm | Nội dung |
| --- | --- |
| `Python/ast_context_slicer.py` | Resolve có trạng thái/provenance; bind đúng; chọn member class trước giới hạn definition |
| `Python/function_methods.py` | Tách tìm ứng viên theo tên khỏi truy xuất code đã resolve |
| `Python/slicing_code_class.py` | Chặn mọi đường ambiguous → full-body; giữ fallback đúng callee |
| `Python/project_kb.py` | Chọn member, giới hạn bản definition candidate ở 16.000 ký tự; giữ KB đầy đủ |
| `Python/export_slices.py` | Truyền scope/masking/config; lưu diagnostics và policy mới |
| `codet5p_type_retrieval/preprocess_generative.py` | Kiểm tra policy và giới hạn 16.000 ký tự/definition trước ghép input; không để nhánh nào vượt trần |
| Công cụ reprocess mới | Inventory, source revision, tái dùng KB, resume, preview và báo cáo |
| Manifest/merge/validator | Phân biệt raw policy cũ/mới; không nhận lẫn dữ liệu chưa sửa |
| Generator + tests | Sinh workflow reprocess khi cần; không sửa tay notebook sinh ra |

Các sửa publisher/recovery đang dở trong workspace là công việc riêng. Trước khi code phải ghi nhận diff và tách phạm vi, không coi chúng là đã test/push hoặc đã được người dùng đồng ý trong kế hoạch này. Không động vào báo cáo/diff khác của người dùng.

## 10. Triển khai theo từng bước để review được

### Bước A — Chốt phương án

Giới hạn definition candidate 16.000 ký tự và KB đầy đủ đã được người dùng yêu cầu; người dùng review phần sửa slice và phương án triển khai còn lại. Chưa thực hiện code/push theo tài liệu trước khi được yêu cầu tiếp.

### Bước B — Code và test local

Sửa resolver/slicer/candidate renderer, thêm regression test, chạy full suite. Không tự chạy Kaggle. Ghi rõ phần nào đã sửa và hạn chế của resolver còn lại.

### Bước C — Preview và kiểm kê dữ liệu cũ

Tạo preview nhỏ có thể review, kiểm kê exact version của 19 inputs, thử khôi phục context trên outlier và nhóm đối chứng. Báo rõ có cần lấy lại source không; xác định quy mô xử lý lại và tài nguyên. Không hứa “chỉ merge lại là xong” khi chưa có bằng chứng.

### Bước D — Người dùng xem kết quả và quyết định triển khai

Cung cấp code commit đã test, before/after, số project/sample cần reprocess, Dataset inputs đã pin version, output dự kiến, kernel/account và dry-run command cụ thể. Đây là điểm dừng trước chạy thật, theo yêu cầu hiện tại của người dùng.

### Bước E — Chạy reprocess khi được phép

Ưu tiên job CPU xử lý lại context từ artifacts + source đúng revision. Nếu dữ liệu quá lớn, chia theo project/partition để resume; số job dựa trên inventory, không mặc định submit 19 notebook cũ.

Nếu người dùng chọn triển khai phân tán trên ba account: giữ owner/visibility và đủ 19 tọa độ trong plan; không quá 5 active jobs/account. Không suy rằng quyền chạy batch trước cho phép tự submit batch mới hoặc phần còn lại. Chỉ chạy batch được người dùng cho phép.

Mọi notebook sửa qua generator, pin code revision, dry-run trước `--push`, dùng publisher của repository và credential helper kiểm tra username; không đọc/in key để kiểm tra thủ công.

### Bước F — Audit, finalize và publish khi được phép

- Audit kết quả xử lý lại toàn bộ sample trước finalize.
- Tái dùng split map/tập holdout hiện tại; verify hash/count/schema/KB coverage.
- Kiểm tra đường dẫn KB không collision khi bỏ qua hoa/thường và index trỏ đúng file sau Kaggle giải nén; không chỉ kiểm tra ZIP local.
- Publish version mới của final Dataset private dưới `duyvu1105` khi người dùng cho phép. Không tạo Dataset mới cùng slug và không coi kernel COMPLETE là bằng chứng publish thành công.
- Xác nhận version đã tiến lên, manifest đúng policy/code/input versions, file listing thực tế và các KB được ánh xạ tồn tại.
- Báo URL/version/status thực tế và những project/sample còn vấn đề. Không tự train.

### Rollback và tái lập

Giữ source Dataset versions, split map, ledger, policy/config và code commit. Output mới ở nơi riêng trước publish; không xóa artifacts cũ. Nếu audit fail, dừng tại output thử nghiệm và báo nguyên nhân, không publish để rồi sửa sau.

## 11. Kết quả cần bàn giao trước lần chạy thật

1. Diff resolver/slicer/candidate và test result.
2. Preview trước–sau hai outlier, kèm provenance hàm và member được chọn.
3. Báo cáo ký tự toàn tập; báo cáo token riêng nếu đã dùng tokenizer cụ thể.
4. Inventory xác định phần có thể tái dùng và phần cần lấy lại source.
5. Manifest/config/schema mới và kiểm tra không trộn raw policy cũ.
6. Kế hoạch chạy cụ thể cùng dry-run output để người dùng xem trước khi yêu cầu triển khai.

**Chưa có lệnh chạy thật nào được thực hiện theo kế hoạch này.**
