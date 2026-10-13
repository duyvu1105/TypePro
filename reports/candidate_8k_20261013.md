# Candidate definition 8k — 2026-10-13

Áp dụng sau target masking/member selection, chỉ trên bản sao candidate:

| Độ dài | Hành vi |
| --- | --- |
| ≤ 8.000 ký tự Unicode | Giữ definition hiện tại |
| > 8.000 ký tự | Rút bằng AST về chữ ký/docstring; class giữ bases và khai báo thuộc tính |
| Summary > 8.000 ký tự | Ưu tiên chữ ký, chỉ thêm các đoạn docstring hoàn chỉnh vừa ngân sách |

Nếu riêng chữ ký vượt ngân sách, bỏ nguyên khai báo từ cuối; header quá dài
hoặc source không parse được nhận omission comment. Không cắt ngang Python.
Signature-list trong KB thư viện được bổ sung `pass` cho header hoàn chỉnh
trước khi parse/rút gọn. Diagnostics ghi mode, số khai báo bỏ và docstring bị rút.

Một helper dùng chung cho project retrieval, final masking/render và preprocess.
Ranking/top-10 dùng dữ liệu trước khi rút; shared KB giữ nguyên. Target/caller
context không áp dụng ngân sách candidate này. Test tiếp tục kiểm tra wildcard
caller, docstring và masking từ bản sửa trước.

Policy: `ast-context-v5-documented-callers-candidate8k`.
Retrieval schema: `typepro-project-kb-top10-generative-v14-candidate8k-signature-docstring`.
Resume/audit/merge/publisher đồng bộ để từ chối raw output từ policy cũ.

- Full suite: **260 passed, 2 skipped**.
- Boundary tests: 7.999/8.000/8.001 và 430.474 ký tự Unicode.
- Có test docstring nhiều đoạn, signature-only KB, class metadata, signature
  quá dài, invalid source, thứ tự ranking, masking, member-selection-first và
  không sửa shared KB/input rows.
- Notebook sinh bằng generator; dry-run **19 jobs, 7/6/6**; account/merge plans
  không có diff. `git diff --check` thành công.
- Chưa push Git/Kaggle, chưa rebuild Dataset hoặc đo accuracy model.
