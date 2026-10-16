# Kiến trúc TypePro

| Phần | Nguồn chính | Trách nhiệm |
| --- | --- | --- |
| Phân tích source | `typepro/analysis/` | AST, slicing, masking, project KB, truy hồi bằng chứng |
| Process data | `typepro/data/` | Metadata, export, split, preprocess, merge, verify |
| Finetune | `typepro/training/` | Generative QLoRA và contrastive ranker |
| Inference | `typepro/inference/` | Model local, ranker, API DeepSeek có resume SQLite |
| Publish | `typepro/publishing/` | Đóng gói và publish shard/final Dataset |
| Dùng chung | `typepro/shared/` | Đọc dữ liệu, chuẩn hóa nhãn, định dạng chat |
| Kiểm tra bằng chứng | `typepro/audit/` | Regression, inventory và replay source |
| Log khi chạy | `typepro/runtime.py` | Lifecycle, revision, trạng thái, exception và console log |
| Cấu hình | `configs/`, `requirements/` | Revision lock, project test và dependency |
| Kiểm thử | `tests/` | Fixtures và kiểm thử CPU; kiểm thử launcher DeepSeek ở `ssh_notebooks/` |
| Môi trường chạy | `kaggle_notebooks/`, `ssh_notebooks/`, `vastai_notebooks/` | Generator, notebook và launcher theo host |

Implementation Python đang dùng nằm trong package `typepro`. Không còn hai thư
mục nguồn cũ hay lớp wrapper tương thích cho chúng. Các module dùng import đầy
đủ theo package. `typepro/__init__.py` không sửa `sys.path`; script chạy trực tiếp
chỉ thêm root repository khi cần.

`python -m typepro COMMAND ...` là điểm vào thống nhất cho các workflow. Import
model GPU chỉ diễn ra khi chọn bước train/infer. Notebook và launcher dùng
đường dẫn mới; thay đổi notebook phải qua generator, không sửa tay artifact.

Luồng dữ liệu chính: `data.prepare` điều phối các subprocess trong `analysis`,
ghi raw slices và project KB, sau đó preprocess/split/verify. Cache phân tích
ghi vào `<work-dir>/analysis_runtime/`, tách khỏi mã nguồn.
`configs/project_revision_lock.json` khóa revision project;
`configs/test_projects.txt` giữ danh sách project được ưu tiên cho tập test.

## Audit khi chạy

Các workflow qua CLI hoặc entry point có `run_main` tạo thư mục riêng trong
`outputs/audit/` (đổi bằng `TYPEPRO_AUDIT_DIR`):

- `run.json`: stage, thời gian bắt đầu/kết thúc, revision Git, PID/rank, exit code,
  trạng thái `running/complete/failed/interrupted` và loại lỗi.
- `console.log`: stdout/stderr Python và traceback; các giá trị secret lấy từ
  environment được che. Không ghi toàn bộ environment hoặc argv vào manifest.

Với nhiều GPU, mỗi process/rank ghi thư mục riêng để tránh ghi đè. Nếu host bị
kill/mất điện, trạng thái có thể còn `running`; đây không phải bằng chứng thành công.
Output subprocess/native code chưa redirect qua Python không được Tee thu
thập; vẫn cần log tmux và log project hiện có.

Audit dữ liệu chi tiết ở work directory: `project_status/*.json`,
`export_summary`, `exporter_tail`, `context_audit.json`, split audit và manifest.
Checkpoint/model, predictions và metrics thuộc thư mục output, không đưa vào Git.
DeepSeek giữ checkpoint SQLite và cấu hình để từ chối resume sai dữ liệu/model.

Các công cụ `python -m typepro.audit.regressions`, `inventory`, `sources` sinh
báo cáo theo đường dẫn `--output`. Chúng kiểm tra bằng chứng trong slice hoặc
candidates; kết quả không chứng minh model dự đoán đúng hay Dataset đủ mẫu.

## Phạm vi và tài liệu

Việc chuyển package giữ chính sách slicing, masking, ranking, candidate 8k và
split hiện hành. Kiểm thử CPU không thay cho build Dataset thật, đối chiếu
3.277 mẫu test v18 hoặc chạy GPU. Job Kaggle đã submit vẫn dùng commit được pin
trong version của chúng cho đến khi chủ động submit lại.

Hướng dẫn sử dụng nằm trong README root và README của từng môi trường.
Báo cáo cũ và hướng dẫn upstream không còn dùng đã được bỏ; nội dung đã commit
còn trong lịch sử Git. Các chỉnh sửa local trước khi dọn có bản dự phòng trong
Git stash. Danh sách test được chuyển sang `configs/` trước khi xóa báo cáo;
Dataset, checkpoint và credential không thuộc phạm vi dọn dẹp này.
