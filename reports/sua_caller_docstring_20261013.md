# Khôi phục caller và docstring — 2026-10-13

## Thay đổi

- Resolver phân tích export từ AST của module project cho wildcard import;
  không import hoặc thực thi code project. Hỗ trợ tên public mặc định,
  `__all__` dạng list/tuple literal và relative import. Binding tường minh
  vô điều kiện có thể ghi đè wildcard đứng trước nó.
- Giữ cơ chế từ chối khi có tên bị che/rebind, nhiều definition cạnh tranh,
  module không có source, export động, chu trình hoặc mutation chưa chắc chắn.
  Re-export hàm qua module trung gian vẫn chưa được mở rộng.
- Target/callee giữ docstring đầu hàm. Caller giữ chữ ký, docstring và thân
  đã giảm theo dependency. Caller opaque chỉ giữ chữ ký/docstring/exact call,
  không kéo toàn bộ thân vào slice. Decorator caller không được chép vào context.
- Target annotation vẫn được mask trong mọi bản sao, kể cả recursive caller.
  Shared AST/KB không bị sửa. Top-10, cap 16.000 ký tự/candidate và một hop giữ nguyên.
- Policy `ast-context-v4-documented-proven-callers`, retrieval schema
  `typepro-project-kb-top10-generative-v13-documented-proven-callers`.
  Đồng bộ resume, audit, merge/publisher và notebook generator để tránh reuse
  hoặc trộn raw slices từ policy cũ. Masking stamp v7 giữ nguyên.

## Replay source thật

- [nicecream-history](https://github.com/altcatalin/nicecream-history/tree/b6f049fabf643a981901366bd4a73f889e4b67cf):
  `api.database.fetch_bookmark` có đủ hai caller ở `api/views.py`:
  `post_user_bookmarks_handler:321`, `delete_user_bookmarks_handler:370`.
- [mort](https://github.com/alexdong/mort/tree/73413622d93edcd321c05910412d4a9a086eccb1):
  `mort.driver.submit_request`, target `targets`, giữ docstring nguyên nghĩa
  (so sánh `ast.get_docstring`), ví dụ browser descriptors và annotation
  `targets: List[Dict]` trong caller. Target annotation được mask.
  Caller ở revision public này tên `capture`, không phải `load_screenshots`
  trong mẫu dataset người dùng; chưa replay đúng checkout lịch sử của mẫu đó.
- Replay chỉ kiểm tra slice với KB rỗng, không chạy model hoặc đo lại accuracy.

## Xác minh

- Full suite: **246 passed, 2 skipped**.
- 24 regression cases mới: wildcard exports/ambiguity/dynamic/cycle/relative,
  hai caller nicecream, bằng chứng tham số mort, masking/AST immutability,
  docstring, opaque caller, signature-only callee và reject policy cũ.
- Notebook sinh lại bằng generator. Dry-run đủ **19 jobs**, phân bố **7/6/6**;
  account/merge plans không có diff. `git diff --check` thành công.
- Chưa push Git/Kaggle, chưa chạy lại Dataset hoặc inference.
