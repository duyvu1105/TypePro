# Rà soát luồng AST context trước triển khai

Ngày: 2026-10-09. Chính sách: `ast-context-v1`.

## Các điểm đã sửa

- Index lịch sử chỉ lưu chữ ký hàm có annotation, không đủ cho full fallback. Bổ sung catalog AST dùng chung; lấy bản định nghĩa đầy đủ rồi mask trước binder/reducer.
- Class definition bị cắt giữa chừng sau 16.000 ký tự. KB mới lưu nguồn class đầy đủ một lần/project; recommendation chọn nguyên method từ đó.
- Annotation return của method trong class có thể thành tín hiệu ranking trong shared KB. Bỏ return annotation khỏi bản class lưu trong KB, tương tự chữ ký hàm top-level.
- Masking bản definition trước đây chỉ bao phủ arg/return. Bổ sung annotation biến để không đưa annotation mục tiêu trở lại từ bản class/callee.
- Target annotation được che trước slicing/retrieval; mọi callee AST lấy từ catalog gốc được mask trong bản copy trước khi chọn statement. Definition trả về tiếp tục đi qua masking cuối cùng.
- Tránh deepcopy AST target có parent links; render/parse bản riêng, không kéo theo toàn project hoặc sửa AST gốc.
- Tăng retrieval schema lên `typepro-project-kb-top10-generative-v10-ast-context`, KB lên `typepro-project-kb-v5-full-class-source`, masking stamp lên v6. Runtime/status/raw rows có policy; merge kiểm tra policy và stamp. Dataset cũ không được resume/merge như dữ liệu mới.

## Luồng cuối

1. Quét/index project và xây KB một lần; solver không dùng annotation để suy luận dữ liệu mục tiêu.
2. Mask annotation mục tiêu trong source overlay của mẫu.
3. Cắt target theo dependency cấp statement; giữ nguyên block điều khiển. Các hiệu ứng không phân tích được dẫn tới full fallback.
4. Tra callee bằng catalog. Chỉ cắt plain function cùng module, không shadow, binding chính xác và không có decorator chưa hiểu. Param theo vị trí/keyword/default được bind bằng AST; mở rộng literal `*`/`**` khi chắc chắn. Trường hợp khác giữ toàn bộ định nghĩa ứng viên khả dụng.
5. Truy hồi/rank từ KB, mask bản định nghĩa trước scoring.
6. Chọn method/thuộc tính của class dựa trên member query hoặc constructor có bằng chứng; mở rộng dependency helper/thuộc tính. Giữ nguyên toàn bộ thân mỗi method được chọn.
7. Mask output lần cuối, render `<mask>` và ghi diagnostics ngoài prompt.

## Bằng chứng kiểm thử

- Bộ test mới kiểm tra positional/keyword/mixed/default, positional-only/keyword-only, literal unpack, unpack động, invalid binding và shadowing/trùng tên.
- Kiểm tra full fallback vẫn có thân hàm annotated; target/callee không lộ target annotation.
- Kiểm tra alias, container mutation, return/exception/None path, nested scope và unknown effects.
- Kiểm tra class dependency closure, giữ nguyên AST thân method, constructor được chọn giữ nguyên mọi statement, class dài hơn 16.000 ký tự.
- Thay target annotation và nhãn vẫn cho cùng slice/recommendation; shared KB và source không bị sửa. Kiểm tra riêng return annotation của method không làm đổi KB.
- Chạy toàn bộ `codet5p_type_retrieval/tests`, cùng dry-run render workflow 19 partitions. Kết quả cuối ghi trong báo cáo triển khai.

## Giới hạn cần hiểu đúng

- Chưa chứng minh Python động không thể có leakage ở mọi dự án; kết luận chỉ áp dụng cho các đường và ca đã rà/test. Không dùng ground truth để resolve, bind hoặc chọn code.
- Phiên bản đầu cắt bảo thủ: chỉ bỏ declaration local literal độc lập; giữ toàn block và fallback toàn hàm nếu gặp statement độc lập có tác dụng phụ chưa biết. Không suy đoán logging là pure.
- Import/receiver/descriptor chưa resolve chắc chắn dùng full fallback, có thể làm input dài hơn representation chữ ký cũ. Chưa có kết quả giảm token toàn dataset hoặc accuracy mới.
- Member kế thừa/động chưa xác định: giữ class đầy đủ khả dụng. Chưa tổng hợp source lớp cha riêng khi lớp cha không nằm trong recommendation.
- Không thay chính sách tokenizer truncation. Full fallback quá dài vẫn có thể bị cắt ở train/inference; diagnostics cho phép đo sau khi dataset mới hoàn tất.
- Luồng Kaggle hiện xuất arg và return. Slicing biến dùng đường statement hiện có, được tăng cường masking; chưa thay toàn bộ bằng reducer mới.

## Đợt triển khai được cho phép

Chỉ 5 physical jobs/account: `duyvu1105`, `duymign`, `vdduy1105`. Tổng 15 jobs, giữ mapping/visibility/partition plan hiện hành. Dùng scheduler với `--jobs-per-account 5`, ledger riêng và source commit đã test/push. Giữ 4 jobs còn lại chờ người dùng yêu cầu; không merge, publish final hoặc train tự động.
