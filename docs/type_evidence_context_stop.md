# Dừng truy context theo bằng chứng type

Triển khai ngày 23/10/2026 trên nhánh `context-type-evidence-stop`, theo yêu cầu tạo nhánh riêng. Context policy: `ast-context-v8-type-evidence-stop`.

Bộ chọn dependency của target return có thể dừng truy phần chỉ tạo giá trị khi gặp builtin scalar đã xác minh (`int`, `str`, `bool`, `float`, `complex`, `bytes`) hoặc return contract scalar cụ thể của hàm sync được resolve đúng. Giữ nguyên phép chuyển đổi/lời gọi làm bằng chứng và signature của helper cần thiết. Không dùng annotation target hoặc gold để quyết định cắt.

Ví dụ source:

```python
def cleanup(raw):
    return raw.strip()
def target(raw) -> <mask>:
    cleaned = cleanup(raw)
    result = int(cleaned)
    return result
```

Slice mới có thể chỉ giữ:

```python
def target(raw) -> <mask>:
    result = int(cleaned)
    return result
```

Đây là đoạn bằng chứng cho dự đoán type, không phải chương trình có thể chạy độc lập. Không thay giá trị bị bỏ bằng literal giả. `int(cleaned)` xác định kết quả là int khi thành công; nguồn tạo giá trị `cleaned` không còn giúp xác định thêm type đó.

Các thành phần của tuple/collection được duyệt riêng: ranh giới đã chứng minh có thể dừng, phần chưa resolve vẫn truy theo dependency cũ. Không khẳng định có bộ suy luận đầy đủ `list[?]` hoặc tự chốt annotation alias.

## Giới hạn để giữ bằng chứng hữu ích

- Không dùng phép ép kiểu để chốt type của **argument**. Giữ mọi cách dùng, contract và caller của argument; phần signature-first của callee tiếp tục hoạt động như trước.
- Không cắt value dependencies của kết quả mutable hoặc nominal class theo return annotation, vì kết quả có thể chia sẻ alias với argument và bị mutation về sau.
- Không dừng tại `Any`, TypeVar, alias chưa mở, `Literal`, contract không xác định, hàm decorated, async, generator hoặc binding không chắc chắn.
- Constructor bị shadow bởi argument, import, wildcard import hoặc assignment không được coi là builtin.
- Giữ nhánh, điều kiện, return/yield/raise và mutation đang được reducer theo dõi. Khi có ranh giới type, giữ toàn bộ finally và các dependency của cleanup.
- Giữ cơ chế fallback cho scope/effect động. Khi không tìm thấy proof, dùng đường dependency cũ.
- Không thay KB schema, nội dung KB, trọng số retrieval, giới hạn candidate hoặc cấu hình model. Không bỏ toàn bộ KB candidate chỉ vì có proof scalar: alias/annotation gốc vẫn có thể cần thông tin khác.

Proof được lưu trong `recommendation_diagnostics.context_reduction`, component `type_evidence`, kèm reason, contract và provenance helper. Đây là bằng chứng theo giả định contract tĩnh hợp lệ, không phải đảm bảo giữ mọi hành vi Python động hay mọi annotation tác giả có thể chọn.

## KB và shard mới

Raw slice/status/runtime phải dùng policy v8; dữ liệu v7 không được coi là slice mới hoặc trộn vào merge v8. KB frozen v7/v8 vẫn được tái sử dụng khi commit project, retrieval schema, KB schema và checksum hợp lệ. Bytes KB được copy nguyên vẹn; import index được phục hồi từ KB. Khi không tương thích, workflow build KB bình thường.

Chạy lại đúng 21 physical jobs của account plan, 7/7/7 trên ba account và tối đa 5 active/account. Source pin vào commit của nhánh mới. Lượt này chạy lại shard; không tự động chạy final merge.

## Kiểm tra

Tests bao gồm builtin bị shadow, contract mở, callback/argument, async/decorator/generator, mutable alias, nhánh chưa biết và None, finally, target masking và shared AST/KB không đổi. Kiểm tra KB reuse so sánh byte-for-byte cho cả policy frozen v7 và v8.

So sánh 9 fixture bảo toàn bằng chứng có sẵn và 2 fixture minh họa ranh giới scalar: tất cả yêu cầu bằng chứng đều pass. Tổng slice giảm từ 2.571 xuống 2.390 ký tự; hai fixture mới giảm 183 → 70 và 154 → 86. Đây là phép đo fixture, không phải mức giảm token toàn dataset hoặc cải thiện accuracy model.

Artifact local: `outputs/audit/type-evidence-stop/comparison.json`.
