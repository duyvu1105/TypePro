# Luồng dự kiến sửa: lấy gì vào slice, lấy gì vào candidate?

**Sơ đồ chỉ mô tả phương án dự kiến sau sửa theo [plan](ke_hoach_sua_phinh_input_20261010.md). Chưa triển khai code.**

```mermaid
flowchart TD
    SRC["SOURCE PROJECT ĐÚNG COMMIT"] --> IDX["Project index / AST<br/>File, module, class, function, import/alias"]
    SRC --> KB[("KB RIÊNG CỦA PROJECT<br/>Class project đầy đủ<br/>Class thư viện đã thu thập từ import<br/>Type alias / re-export alias<br/>Kiểu từ constructor trong thân hàm")]
    SRC --> TARGET["Xác định target: param / return / biến<br/>Đúng file, class/function và vị trí<br/>Che annotation cần dự đoán"]

    subgraph S["A. SLICE — CODE CÓ BẰNG CHỨNG LIÊN QUAN"]
        TARGET --> CORE["1. Code của target<br/>Chữ ký đã mask + câu lệnh liên quan<br/>Gán, sử dụng, return/yield, điều kiện,<br/>alias và mutation/phụ thuộc cần thiết"]
        CORE --> SAFE{"AST cắt chắc được?"}
        SAFE -- "Có" --> RED["Giữ phần target liên quan"]
        SAFE -- "Không" --> WHOLE["Giữ nguyên target function đã mask<br/>Biến global: giữ context liên quan trong scope"]
        TARGET --> IMPORTS["2. Import / from-import / alias<br/>Cần để hiểu tên và kiểu trong context"]
        TARGET --> CLASSCTX["3. Ngữ cảnh class nếu cần<br/>Class bao quanh / class được tham chiếu chắc chắn<br/>Header, thuộc tính và member liên quan<br/>Không chèn class chỉ vì giống tên target"]

        RED --> CALL["4. Lời gọi còn trong target slice<br/>Tra index bằng tên + scope + import + receiver"]
        WHOLE --> CALL
        IDX --> CALL
        CALL --> RESOLVE{"Xác định chắc đúng<br/>hàm được gọi?"}
        RESOLVE -- "Không" --> UNK["Giữ lời gọi vốn có<br/>Không thêm thân các hàm chỉ khớp tên"]
        RESOLVE -- "Có" --> SOURCEOK{"Có source của đúng hàm?"}
        SOURCEOK -- "Không" --> SIG["Giữ lời gọi / chữ ký có sẵn<br/>Ghi source thiếu"]
        SOURCEOK -- "Có" --> BIND{"Bind đúng param và<br/>AST reduction chắc chắn?"}
        BIND -- "Có" --> CALLEE["Thêm phần code liên quan của đúng hàm<br/>Chữ ký, param và bằng chứng kết quả cần thiết"]
        BIND -- "Không" --> FULL["Thêm nguyên đúng hàm đã resolve<br/>Không lấy các hàm khác cùng tên"]

        TARGET --> USE["5. Nơi gọi target, nếu có<br/>Chỉ lấy call site xác định đúng target<br/>Đối số truyền vào + câu lệnh tạo giá trị đó<br/>Chữ ký hàm hỗ trợ chỉ khi resolve đúng"]
        IDX --> USE

        IMPORTS --> JOIN["GHÉP SLICE<br/>Target + import + class context cần thiết<br/>+ callee đã resolve + caller context đã xác minh<br/>Loại trùng theo định danh source"]
        CLASSCTX --> JOIN
        RED --> JOIN
        WHOLE --> JOIN
        UNK --> JOIN
        SIG --> JOIN
        CALLEE --> JOIN
        FULL --> JOIN
        USE --> JOIN
    end

    subgraph C["B. CANDIDATE — KIỂU / CLASS CÓ THỂ PHÙ HỢP"]
        TARGET --> SIGNAL["Bằng chứng từ target đã mask<br/>Tên target, member/thuộc tính được dùng,<br/>constructor, alias, kiểu nhìn thấy và source flow"]
        JOIN --> SIGNAL
        UNK -. "Tên method vẫn là bằng chứng để xét kiểu" .-> SIGNAL
        SIGNAL --> SEARCH["Tìm ứng viên trong KB của đúng project<br/>Import/alias khớp chính xác<br/>Class/kiểu xuất hiện trong context<br/>Tên gần giống, member phù hợp, cấu trúc/BM25"]
        KB --> SEARCH
        SEARCH --> RANK["Xếp hạng + loại trùng qualified name<br/>CHỌN TỐI ĐA 10 CANDIDATE<br/>Không thêm candidate theo đáp án gold"]
        RANK --> COPY["Lấy bản copy definition đầy đủ từ KB<br/>Mask target trong bản copy"]
        COPY --> ISCLASS{"Class của project?"}
        ISCLASS -- "Có" --> MEMBERS{"Chọn chắc member liên quan?"}
        MEMBERS -- "Có" --> SELECT["Chọn method / thuộc tính<br/>Thêm constructor/helper phụ thuộc cần thiết<br/>Giữ nguyên thân method ở bước chọn"]
        MEMBERS -- "Không" --> FALLBACK["Dùng definition class đầy đủ đã mask<br/>Vẫn bắt buộc qua bước cắt bên dưới"]
        ISCLASS -- "Không" --> OTHER["Definition class thư viện / type alias<br/>/ re-export alias / kiểu từ thân hàm"]
        SELECT --> CAP["GIỚI HẠN MỖI DEFINITION<br/>definition = rendered_definition[:16000]<br/>Tối đa 16.000 ký tự, kể cả fallback<br/>Không cắt KB gốc"]
        FALLBACK --> CAP
        OTHER --> CAP
        CAP --> RECS["recommendation_types<br/>Tối đa 10 ứng viên<br/>Mỗi ứng viên: type/name, qualified name,<br/>definition đã cắt và metadata cần thiết"]
    end

    TARGET --> HEADER["Tên target + tên function + scope"]
    HEADER --> INPUT["INPUT CHO MODEL<br/>TARGET HEADER + SLICE + CANDIDATE"]
    JOIN --> INPUT
    RECS --> INPUT
    LABEL["LABEL / ĐÁP ÁN<br/>Lưu riêng, không dùng để chọn context"] --> RECORD["RECORD DATASET<br/>Input + label riêng + metadata/diagnostics"]
    INPUT --> RECORD
```

## Cách đọc

| Phần | Những gì được lấy |
| --- | --- |
| **Slice: target** | Chữ ký đã mask và các câu lệnh phục vụ suy luận kiểu; không cắt chắc thì giữ target function |
| **Slice: ngữ cảnh tên/class** | Import, alias, class header, thuộc tính/member thực sự cần để hiểu context; không lấy class đoán theo tên |
| **Slice: hàm được gọi** | Chỉ code của callee đã resolve đúng; bind/cắt không chắc thì giữ nguyên đúng hàm đó |
| **Slice: nơi gọi target** | Đối số và code tạo ra chúng từ call site đã xác định đúng target; không gom nơi gọi chỉ vì trùng tên |
| **Candidate: nguồn** | Class project, class thư viện trong KB project, type alias, re-export alias, kiểu suy từ constructor trong thân hàm; không lấy kiểu từ return annotation |
| **Candidate: giới hạn** | Tối đa 10; mỗi `definition` lấy tối đa 16.000 ký tự **sau chọn member/masking**, kể cả fallback |
| **KB** | Class project vẫn đầy đủ để các mẫu khác chọn member; không ghi definition đã cắt ngược vào KB |

Các nguồn trên là những phần **có thể được lấy khi có bằng chứng và đúng scope**; không phải mẫu nào cũng chứa đủ mọi phần. Nhánh biến global áp dụng khi scope đó được cấu hình export. Callee chỉ mở rộng một hop; không quét đệ quy mọi lời gọi trong thân callee vừa thêm.

**Ba ranh giới cần giữ:**

- Các hàm khớp tên là ứng viên tra cứu nội bộ, không tự thành thân hàm trong slice hoặc danh sách recommendation. Function signature có thể nằm trong index/KB để tra cứu nhưng không tự là candidate kiểu.
- Nếu target chính là receiver chưa biết kiểu, không dùng một class candidate như kiểu đã biết để resolve method của nó. Candidate có thể dùng cùng bằng chứng member mà vẫn chỉ là giả thuyết.
- Trần 16.000 chỉ dành cho từng candidate definition; không tính tên/tag và không áp lên KB hoặc slice. Cắt chuỗi có thể dừng giữa method; tối đa 10 definition vẫn có thể dài tổng cộng 160.000 ký tự. Không coi đó là số token hay bảo đảm vừa context model.

`other_prompt` và diagnostics có thể lưu ở raw output để kiểm tra nhưng không phải section của input generative đang đề xuất. Độ dài, lý do fallback và provenance được lưu riêng; preprocess kiểm tra lại trần definition trước khi ghép input.
