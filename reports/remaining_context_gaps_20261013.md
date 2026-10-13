# Kiểm tra thêm phần code cũ có nhưng hiện tại thiếu — 2026-10-13

Đối chiếu snapshot `83fc6619175a52f9f59e00a238e1e821563abf75` và working tree
trên cùng source tối giản tìm được **6 mẫu bổ sung** có bằng chứng trong prompt
cũ nhưng thiếu trong prompt hiện tại. Đây là audit bổ sung; không thay thế hoặc
phủ định kết quả 9/9 regression và 9/9 upstream trước đó. Chưa sửa pipeline trong
lượt kiểm tra này, chưa chạy model hoặc replay toàn bộ Dataset.

Prompt ở đây là slice cộng definitions của candidates, không chỉ slice. File
[JSON đối chiếu](remaining_context_gaps_20261013.json) chứa output của hai bản.

| Mẫu bổ sung | Snapshot cũ | Hiện tại | Nguyên nhân |
| --- | --- | --- | --- |
| Stub thư viện: `from extlib import decode`, contract `decode(value: bytes) -> str` | Có chữ ký | Thiếu cả trong slice/candidates | Resolver chỉ có AST project, không dùng contract từ third-party KB |
| Receiver method: `obj.normalize(value)` với method `-> str` | Có chữ ký từ lookup tên | Thiếu `-> str` trong prompt | Receiver chưa resolve; KB class bỏ return annotations nên candidate cũng không bù được |
| Alias union: `Trivia = Space | Comment`, hai operand là class đã khai báo | Có alias | Thiếu alias | Nhận diện implicit alias chưa chấp nhận tên class project làm operand union |
| Alias typing: `Job = Awaitable[str]` | Có alias | Thiếu alias | `Awaitable` chưa nằm trong whitelist `TYPE_FORMS` |
| `if True: def normalize(value: str): ...` | Có chữ ký | Thiếu chữ ký | Catalog không nhận definition trong block; resolver trả `conditional_definition` |
| Comment class: `# token holds a text identifier` cạnh field | Có trong candidate | Thiếu | KB class chuyển từ source segment sang `ast.unparse`, làm mất comment |

Ví dụ `Trivia = Space | Comment` chỉ minh họa một dạng bị lọt; không phải xác minh
sample `Trivia` trong Dataset của người dùng, vì chưa có source của sample đó.

Một control bổ sung gọi helper từ trong lambda không có chữ ký ở cả hai snapshot;
không tính nó là regression do thay đổi mới. Sibling lambda làm mất chữ ký callee
ngoài lambda đã được sửa và kiểm tra trong bộ regression trước.

## Phân biệt lý do thiếu

- Alias union giữa class project và `Awaitable[...]` là thiếu coverage nhận diện
  alias có thể mở rộng bằng kiểm tra binding, không cần đọc target annotation.
- External contract có thể giữ lại khi xác minh đúng package/module/function
  và provenance của stub. Không bật lại lookup theo tên ngắn trên mọi package.
- Lookup method theo tên ngắn ở bản cũ có thể trỏ nhầm implementation. Phần
  hữu ích nên được đưa về resolver receiver/class/MRO và signature-only contract;
  dynamic receiver chưa xác định vẫn không đủ cơ sở để chèn guessed body.
- `if True` là trường hợp có thể xác minh tĩnh. Điều kiện runtime tổng quát hoặc
  nhiều binding cạnh tranh cần giữ guard/provenance và xử lý bảo thủ riêng.
- Comment là thông tin khác docstring. Docstring đang được giữ, nhưng comment
  có thể chứa mô tả kiểu và vẫn bị mất khi unparse. Muốn giữ cần gắn source
  comment liên quan với AST node đã chọn và tính vào budget candidate.

## Phần bỏ có chủ đích vẫn khác bản cũ

Candidate lớn hơn 8k dùng chữ ký/docstring; thân method, các đoạn docstring không
vừa budget hoặc khai báo cuối khi riêng signatures quá dài có thể bị bỏ. Ngoài
ra, class giống tên chỉ là candidate; statement không liên quan, guessed callee
và expansion nhiều hop không được đưa trở lại slice theo đường cũ.

## Ưu tiên tiếp theo

1. Mở rộng alias bằng binding/type-expression chung và nối external contracts
   có module-qualified provenance vào resolver. Thêm các mẫu trên vào regression.
2. Resolve receiver có cơ sở từ source (`self`/`cls`, construction hoặc non-target
   contract đã biết), rồi thêm conditional definitions xác minh được tĩnh.
3. Giữ comment liên quan bằng source spans, bên cạnh docstring đã giữ.

Kết quả 299 test hiện có chỉ chứng minh các điều kiện đã được assert. Sáu mẫu
mới chưa nằm trong full suite; chúng đã được chạy đối chiếu độc lập để chỉ ra
phần thiếu trước khi triển khai thêm.
