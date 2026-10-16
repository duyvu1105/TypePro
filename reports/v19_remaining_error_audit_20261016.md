# Rà soát lỗi export và fallback v19 — 16/10/2026

## Lỗi đã tái hiện và sửa

1. **File target vắng trong catalog gây `KeyError`.** Bản sửa ở lượt trước được giữ nguyên: tạo catalog riêng từ source đã masking của đúng file target; không sửa catalog/KB dùng chung. Bốn regression kiểm tra arg/return với catalog rỗng hoặc thiếu file. Replay trước đó export được 302/302 slice thật từ sáu project, chưa phải chạy đầy đủ retrieval/preprocessing.
2. **Cache caller bị lưu dở khi annotation timeout hoặc có exception.** Trước sửa, `FunctionCatalog.callers()` gán `self.callers_cache = {}` trước khi quét và bổ sung từng caller vào cache chung. Nếu quét bị ngắt sau caller đầu tiên, lần gọi sau dùng luôn cache thiếu và không quét lại. Test tái hiện bằng cách ngắt lần resolve thứ hai: trước sửa chỉ còn 1/2 caller; sau sửa lấy đủ 2/2. Bản sửa xây caller/rejection cache cục bộ và chỉ công bố sau khi hoàn thành toàn bộ scan. Đây là lỗi mất bằng chứng được tái hiện bằng test, chưa có log chứng minh nó đã xảy ra trong Dataset v19.

## Bổ sung chẩn đoán

Exporter giữ các trường tổng kết cũ, thêm `empty_slices`, `exceptions_by_type` và `local_catalog_fallbacks`. Nhờ đó có thể tách annotation không có slice, timeout, và exception; theo dõi số mẫu được cứu bởi fallback.

`prepare_dataset.py` trích JSON tổng kết từ `exporter_tail` vào `project_status/*.json` dưới trường `export_summary`. Đọc được cả summary của exporter cũ; nếu không tìm thấy thì ghi `null`, không diễn giải là không có lỗi. Không thay đổi nhãn, split hay bộ lọc mẫu.

Test chạy luồng exporter với lần lượt slice rỗng, timeout, `KeyError`, rồi mẫu thành công: xác nhận tiếp tục export được mẫu cuối và thống kê đúng từng nhóm. Test parser kiểm tra log có nhiễu và summary bị thiếu.

## Kiểm chứng và giới hạn

- Toàn bộ suite: **348 passed, 2 skipped** (`python -m pytest codet5p_type_retrieval/tests -q -p no:cacheprovider`).
- `git diff --check` trên các file code sửa: không có lỗi whitespace.
- Không sửa generator/notebook, không push Git/Kaggle, chưa thay đổi Dataset đã publish.
- Các lỗi nguồn không tồn tại tại commit đã khóa (`FileNotFoundError`), lỗi fetch commit và project KB timeout 300 giây vẫn cần xử lý theo từng trường hợp; các sửa đổi trên không chứng minh đã khắc phục chúng.
- Chưa xác minh toàn bộ 3.277 mẫu test v18 qua pipeline hoàn chỉnh. Cần build lại và đối chiếu từng mẫu để xác nhận độ phủ cuối cùng.
