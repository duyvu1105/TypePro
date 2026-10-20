# Chấm điểm và chia ký tự cho candidate

Chính sách `candidate-symbol-v2` áp dụng khi xuất candidate mới. Nguồn triển
khai là `typepro/analysis/candidate_policy.py`; `project_kb.py` điều phối việc
chấm điểm trên KB của chính project. Không tính token, không dùng tokenizer.

## 1. Công thức và threshold

Mỗi đầu điểm nằm trong đoạn 0–1:

```text
score = 5 × direct
      + 3 × usage
      + 2 × symbol
      + 2 × bm25
      + 1 × name
      + 0,5 × import
```

Điểm tối đa theo công thức là 13,5. Điểm không phải xác suất dự đoán đúng.
Chỉ nhận candidate có `score >= 1.0` (bao gồm đúng 1 điểm), lấy tối đa 10.
Trọng số và threshold là cấu hình được yêu cầu, chưa phải kết quả tối ưu trên
validation hoặc bằng chứng tăng accuracy.

| Đầu điểm | Cách tính giá trị 0–1 | Weight |
| --- | --- | ---: |
| `direct` | 1 nếu tìm được constructor gắn với đúng target bằng binding đã xác minh; ngược lại 0 | 5 |
| `usage` | Số member target sử dụng mà candidate có / tổng số member target sử dụng; không có member truy vấn thì 0 | 3 |
| `symbol` | 1 nếu symbol đã resolve nằm trong biểu thức tạo giá trị cho target; 0,5 nếu trong code thực thi khác của hàm target; còn lại 0 | 2 |
| `bm25` | BM25 đối xứng chuẩn hóa `raw / (raw + 1)` giữa slice và definition đã mask | 2 |
| `name` | `SequenceMatcher.ratio()` giữa tên target và tên ngắn candidate, sau khi chuyển chữ thường và bỏ ký tự ngoài ASCII chữ/số | 1 |
| `import` | 1 nếu from-import tường minh đúng candidate (kể cả không dùng/chỉ để annotation), hoặc truy cập symbol thực tế qua module import trong thân hàm target; binding không bị che/gán lại; còn lại 0 | 0,5 |

Các tín hiệu được cộng đồng thời; không có khoản thưởng 10.000 cho việc xuất hiện
trong danh sách seed. Không có hai vị trí ưu tiên member bên ngoài công thức.
Candidate bằng điểm được xếp theo qualified name không phân biệt hoa/thường.
Loại trùng theo qualified name không phân biệt hoa/thường.

Ví dụ: `direct=0`, `usage=0.5`, `symbol=0`, `bm25=0.4`, `name=0.6`, `import=1`:

```text
score = 0 + 1,5 + 0 + 0,8 + 0,6 + 0,5 = 3,4 → đủ điều kiện
```

Chỉ import mà không có tín hiệu khác: 0,5 điểm, không đủ điều kiện. Tên giống
hoàn toàn và không có tín hiệu khác: 1 điểm, đủ điều kiện. Không candidate nào
đạt ngưỡng thì xuất danh sách rỗng, vẫn giữ mẫu với slice và label hợp lệ.

## 2. Nguồn của từng tín hiệu

### Bằng chứng trực tiếp

Ví dụ:

```python
from external import Client as C

def fetch(client: <mask>):
    return client.get('/users')

fetch(C())
```

Catalog phải resolve được lời gọi tới đúng `fetch`, bind đối số vào đúng
parameter `client`, rồi resolve constructor `C` tới `external.Client`. Khi đó
candidate tương ứng có `direct=1`. Chỉ thấy từ `Client` trong slice không đủ.

Hỗ trợ đối số positional/keyword qua binder hiện có, biến được gán constructor
một lần trong thân thẳng trước lời gọi, và factory không có parameter đã resolve
mà các `return` tường minh cùng trỏ tới một constructor. Theo factory tối đa 4
mức. Với target return, kiểm tra constructor trong các return của chính hàm.

Không đọc annotation để tính direct. Receiver chưa resolve, binding mơ hồ,
gán lại, tác động động, import local trong hàm, default argument không truyền
tường minh và factory có parameter không được đoán thành bằng chứng trực tiếp.
Không tìm được bằng chứng có nghĩa là đầu điểm này bằng 0, không loại toàn bộ
candidate khỏi các đầu điểm khác. Đây là bằng chứng về cách dùng quan sát được,
không khẳng định constructor đó là kiểu duy nhất có thể truyền vào parameter.

### Khớp cách sử dụng

Truy vấn lấy từ member access trên target và các alias đơn giản đã được bộ
phân tích hiện có theo dõi. Ví dụ target dùng `get` và `close`; candidate có
`get` nhưng không có `close` thì `usage=1/2`. Member kế thừa lấy từ metadata KB.
Nếu thiếu metadata member, đọc method và thuộc tính `self`/`cls` từ AST definition.
Đầu điểm này hiện dùng cho target parameter; target return không tự suy đoán
receiver usage mới. Tên member trùng là tín hiệu cấu trúc, không chứng minh
hai class có cùng ngữ nghĩa.

### Symbol và import

`symbol` resolve Name/Attribute tới đúng qualified name trong KB; không khớp
bằng tên ngắn. Return expression và đối số bind vào đúng target parameter tại
caller đã resolve nhận mức 1. Theo biến trung gian tối đa 16 tên, chỉ khi có
một binding từ assignment vô điều kiện trước điểm dùng. Symbol ở phần executable
khác của hàm target nhận 0,5. Lấy mức cao nhất, không cộng theo số lần xuất hiện.
Không đi vào annotation, docstring, nested function/class/lambda hay comprehension.
Không giả định fluent method trả về receiver; symbol không phải bằng chứng direct.

`from argparse import Namespace as NS` cho candidate `argparse.Namespace`
import=1 kể cả NS chỉ dùng để annotation hoặc hoàn toàn chưa dùng. Với
`import pandas as pd`, chỉ candidate được tham chiếu và resolve thực tế như
`pd.DataFrame` mới nhận import=1; không thưởng cho cả danh mục `pandas.*`.
Gán receiver attribute như `self.value = value` không tự vô hiệu điểm của
from-import chưa dùng; shadow/rebind và thao tác namespace động vẫn bị chặn.
Giữ giới hạn resolver hiện có: import module-level, binding không bị che/gán
lại, identity qualified chính xác; chưa resolve public re-export tổng quát.

### BM25

Tách token identifier bằng regex, chuyển chữ thường và bỏ từ khóa cấu trúc như
`class`, `def`, `return`, `self`. Dùng hàm `BM25.py` hiện có trên từng cặp văn bản,
với `k1=1.5`, `b=0.75`, trung bình điểm hai chiều rồi chuẩn hóa `raw/(raw+1)`.
Đây là biến thể BM25 theo cặp, không phải IDF tính trên toàn bộ kho candidate.
Input rỗng hoặc chỉ còn từ bị loại nhận 0 điểm BM25.

BM25 được tính trên definition đầy đủ đã mask, trước rút gọn ký tự. Nhánh BM25
cũ của slicer vẫn có thể tìm seed với ngưỡng >0,1, nhưng seed và điểm ở nhánh đó
không vượt qua hoặc thay thế công thức cuối. Bước cuối chấm trực tiếp trên các
record candidate trong KB project; không dùng vị trí seed để cộng điểm.

### Chống rò rỉ nhãn

Hàm chấm điểm không nhận `label`, `gttype` hoặc `origttype`. Annotation target
được mask trước khi dùng definition để tính điểm. KB, AST và source gốc không
bị sửa bởi việc chọn/rút gọn. Docstring và ngữ cảnh nguồn vẫn là bằng chứng
hợp lệ; không xóa chỉ vì chúng chứa tên kiểu giống nhãn.

## 3. Các giới hạn ký tự

| Phạm vi | Giới hạn |
| --- | ---: |
| Số candidate | 0–10 |
| Toàn bộ section candidates đã render | 16.000 ký tự |
| Definition của từng candidate | 4.000 ký tự |
| Phần ngắn ban đầu của mỗi candidate, gồm tag và định danh | 600 ký tự |

Đếm bằng `len()` của chuỗi Python Unicode, không phải số byte UTF-8. Tổng gồm
`[RECOMMENDATION_TYPES]`, newline, `[TYPE]`, `[QUALIFIED_NAME]`, `[DEFINITION]`,
tên và nội dung definition. Metadata audit trong JSON như score không được
đưa vào prompt, nên không thuộc section này.

Không tính slice, target header hoặc output vào 16.000 ký tự. Giới hạn ký tự
không bảo đảm vừa cửa sổ token; thay đổi này không sửa train/inference.

## 4. Cách chia ngân sách

1. Xếp hạng các candidate đạt threshold. Chạy bộ chọn member AST hiện có trên
   bản sao definition; giữ các member liên quan và phụ thuộc của chúng.
2. Tạo bản definition tối đa 4.000 ký tự. Nếu quá dài, dùng signature summary,
   docstring theo đoạn hoàn chỉnh và khai báo nguyên vẹn. Với class, khôi phục
   thân method nguyên vẹn khi còn chỗ. Không cắt chuỗi giữa signature.
3. Tạo phần ngắn tối đa 600 ký tự cho mỗi candidate, gồm tag/định danh và phần
   definition vừa chỗ. Nếu ngay cả khai báo có nghĩa không thể giữ được thì bỏ
   candidate và xét candidate tiếp theo trong thứ hạng.
4. Trừ header, newline và tổng phần ngắn khỏi 16.000 để có ngân sách còn lại R.
5. Chia phần bổ sung theo `R × score_i / tổng score` của các candidate còn có
   nội dung để giữ. Mỗi candidate chỉ nhận tới độ dài definition tối đa 4.000.
6. Candidate ngắn hoặc chạm trần trả phần dư cho các candidate còn lại. Làm tròn
   xuống số ký tự nguyên; ký tự lẻ ưu tiên theo thứ tự xếp hạng.
7. Render các khai báo vừa ngân sách. Nếu khối AST không vừa, không cắt ngang
   khối đó. Phần chỗ trống được đề nghị chia lại tối đa 10 vòng; dừng khi không
   thể thêm nội dung hoàn chỉnh. Không bắt buộc dùng hết 16.000 ký tự.
8. Đo lại section cuối cùng để bảo đảm không vượt trần.

Ví dụ 10 candidate có phần ngắn thực tế 400 ký tự/candidate: trừ cả header và
10 newline thì R khoảng 11.969 ký tự. Nếu tổng điểm là 36, candidate 8 điểm
được đề nghị thêm khoảng `R × 8/36`, candidate 2 điểm khoảng `R × 2/36`.
Kết quả thực tế có thể ngắn hơn vì giới hạn 4.000, độ dài nguồn và ranh giới AST.

## 5. Metadata và tương thích pipeline

Candidate mới lưu `score`, `score_components`, `character_budget` và thông tin
`definition_reduction`. Budget ghi độ dài nguồn trước giới hạn, độ dài phần ngắn,
ngân sách definition được cấp, độ dài đầu ra và việc có rút gọn hay không.
Điểm luôn tính trước khi rút gọn; không chấm lại dựa trên bản summary.

Exporter gắn `candidate_policy_version=candidate-symbol-v2`. Runtime/project
status cũng ghi policy; build có cache policy cũ phải xuất lại candidates.
Preprocess, split eligibility, merge, audit và verify hỗ trợ candidate rỗng và
giới hạn mới. Qualified name được hiển thị trong prompt để phân biệt tên ngắn
trùng nhau. Nhãn đầu ra không bị đổi sang qualified name.

Preprocess có thể giới hạn lại candidate của raw cũ nhưng không thể khôi phục
bằng chứng từ source hoặc tính lại 6 đầu điểm nếu thiếu source/KB. Muốn có bộ
điểm mới đầy đủ phải chạy exporter từ source đã khóa revision. Dataset v19 đã
publish không được thay đổi bởi sửa code local này.

Build mới invalidate cache policy v1 qua runtime/project status. Merge từ chối
trộn policy giữa shard hoặc raw/runtime không khớp. Verify vẫn kiểm tra giới
hạn ký tự cho v1 và v2. Preprocess giữ provenance policy cũ của raw, không tự
coi dữ liệu cũ là v2. Hàm scoring/evidence/selector nhận `policy='candidate-weighted-v1'`
để replay baseline, không thay đổi dataset v20/v22 đã có hoặc job đang chạy.

## 6. Kiểm thử

`tests/test_candidate_policy.py` kiểm tra công thức, threshold đúng 1 điểm,
seed không vượt threshold, tie/dedup, constructor/keyword/alias và binding bị
che, giới hạn 16.000/4.000/600, chia theo điểm, Unicode, candidate rỗng và việc
không thay đổi dữ liệu nguồn. Các kiểm thử masking/budget/split hiện có được
cập nhật theo hợp đồng mới. Chạy toàn bộ:

```powershell
python -m pytest tests -q -p no:cacheprovider
```

Kiểm thử symbol/import: `tests/test_candidate_symbol_policy.py`. Đo ablation
trên validation bằng `python -m typepro.audit.candidate_symbol --help`; runner
so v1, symbol-only, import-only và bản kết hợp. Hệ số symbol=2 là cấu hình
được yêu cầu, chưa chứng minh cải thiện accuracy mô hình.
