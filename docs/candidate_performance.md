> Tài liệu lịch sử cho tối ưu policy v1. Policy mặc định mới là
> `candidate-symbol-v2`; xem `candidate_scoring.md`. Các differential tests
> vẫn kiểm tra v1 bằng tham số policy tường minh.

# Tối ưu candidate mà giữ nguyên kết quả

Bản tham chiếu là commit `41b434e`, policy `candidate-weighted-v1`. Tối ưu không
đổi weight, threshold, thứ tự cộng điểm, thứ tự xếp hạng, tie-break, tập candidate
được chấm, cách mask hay ngân sách 16.000/4.000/600 ký tự. Retrieval schema v17
và revision lock của source project được giữ nguyên để merge cùng shard cũ.

## Công việc được tái sử dụng

- BM25 giữ nguyên chuỗi token có lặp và thứ tự token. Chỉ phép kiểm tra một từ
  có xuất hiện trong document dùng `frozenset`; số lần xuất hiện vẫn lấy từ
  `Counter`, độ dài vẫn tính tất cả token, kể cả token lặp. Công thức và thứ tự
  cộng điểm ở cả hai chiều không thay đổi.
- Token, tập từ và Counter của BM25 được cache theo chính xác chuỗi đầu vào.
  Dữ liệu cache chỉ được đọc bên trong BM25, không sửa hoặc trả ra ngoài.
- Query của slice được chuẩn hóa một lần trước vòng duyệt KB. Definition được
  chuẩn hóa/cache theo toàn bộ nội dung đã mask, không cache bằng tên lớp.
- Metadata member suy ra từ AST được cache dưới dạng `frozenset`, không chia sẻ
  AST mutable. Member đã có trong record vẫn được dùng như trước.
- Kết quả render summary được cache theo `(definition, maximum)`. Chỉ chia sẻ
  chuỗi bất biến. Candidate JSON và metadata ngân sách vẫn được tạo bằng bản sao.
- Kiểm tra opaque scope được tái sử dụng trong cùng một lần lấy source evidence;
  cache không tồn tại giữa các mẫu hay các source overlay khác nhau.

Cache toàn cục chỉ nhận chuỗi dài tối đa 32.768 ký tự; văn bản lớn hơn vẫn đi
qua đúng hàm tính cũ, không bị cắt ngắn. Cache BM25/member tối đa 128 entry,
cache chuẩn hóa/summary tối đa 256 entry. Eviction chỉ thay đổi thời gian tính.
Không có trường cache nào được thêm vào KB, raw slice hoặc input của mô hình.

## Kiểm chứng không đổi kết quả

`tests/fixtures/candidate_weighted_v1_reference.py` giữ nguyên các hàm tham chiếu
từ commit cũ. Import cục bộ trong `top_project_types` được bỏ để hàm tham chiếu
gọi các hàm tham chiếu trong cùng fixture, thay vì gọi nhầm code đã tối ưu.

`tests/test_candidate_exact_optimization.py` đối chiếu:

- Điểm BM25 bằng `float.hex()` cho cả hai chiều, nhiều phương thức chuẩn hóa,
  tùy chọn raw, token lặp, Unicode, input rỗng và input vượt kích thước cache.
- Toàn bộ JSON candidate: score, từng đầu điểm, thứ tự, definition, metadata
  rút gọn và phân bổ ký tự; kiểm tra khi cache lạnh và nóng.
- Chuỗi prompt được render từ candidate giống hệt.
- Signature quá dài, code chưa hoàn chỉnh, nhiều mức ngân sách, masked content
  khác nhau và bảo vệ kết quả trước mutation của JSON từ lần gọi trước.
- Chín fixture source của pipeline với cả source evidence và candidate ranking
  tham chiếu, cùng kiểm tra annotation masking hiện có.
- Merge fixture chứa raw slice sinh từ bản cũ và bản tối ưu qua merger thật,
  với cùng retrieval schema, context/masking policy và project revision lock.

Thời gian chạy và revision của code phân tích trong log/provenance sẽ khác.
Đây không phải thay đổi input/label của mô hình hoặc revision source project.
Kiểm thử không thay thế việc xác minh manifest thực tế sau khi job hoàn tất;
benchmark cục bộ cũng không dự đoán chính xác thời gian toàn bộ shard Kaggle.

## Chạy kiểm thử

```powershell
python -m pytest tests/test_candidate_exact_optimization.py -q -p no:cacheprovider
python -m pytest tests -q -p no:cacheprovider
```
