# Kiến trúc TypePro

| Phần | Nguồn chính | Trách nhiệm |
| --- | --- | --- |
| Phân tích source | `Python/` | AST, slicing, masking, project KB, evidence |
| Process data | `typepro/data/` | Metadata, export, split, preprocess, merge, verify |
| Finetune | `typepro/training/` | Generative QLoRA và contrastive ranker |
| Inference | `typepro/inference/` | Model local, ranker, API DeepSeek có resume SQLite |
| Publish | `typepro/publishing/` | Đóng gói và publish shard/final Dataset |
| Log và audit | `typepro/runtime.py` | Console log, lifecycle, revision, trạng thái, exception |
| Môi trường chạy | `kaggle_notebooks/`, `ssh_notebooks/`, `vastai_notebooks/` | Generator, notebook, runner và cấu hình host |
| Hỗ trợ chuyển tiếp | `codet5p_type_retrieval/` | Script tương thích, utilities dùng chung, evidence checks và tests |

Logic của 12 module đã chuyển vào package theo chức năng. Script cũ chỉ chuyển
đến module mới; import cũ trả về cùng module để giữ các caller và monkeypatch.
Các utilities chưa chuyển vẫn được dùng chung, không sao chép thành bản thứ hai.
`typepro/__init__.py` thiết lập đường dẫn hỗ trợ cho giai đoạn chuyển tiếp này.

`python -m typepro COMMAND ...` là điểm vào thống nhất. Import model GPU chỉ diễn
ra khi chọn bước train/infer; process data và trợ giúp chung không cần tải model.
Các notebook cũ vẫn gọi được script tương thích. Chỉ sửa notebook qua generator.

## Audit khi chạy

Mỗi lệnh CLI/script tương thích tạo một thư mục riêng trong `outputs/audit/`
(đổi bằng `TYPEPRO_AUDIT_DIR`):

- `run.json`: stage, thời gian bắt đầu/kết thúc, revision Git, PID/rank, exit code,
  trạng thái `running/complete/failed/interrupted` và loại lỗi.
- `console.log`: stdout/stderr Python và traceback; các giá trị secret lấy từ
  environment được che. Không ghi environment hoặc toàn bộ argv vào manifest.

Với nhiều GPU, mỗi process/rank ghi thư mục riêng để tránh ghi đè. Nếu host bị
kill/mất điện, trạng thái có thể còn `running`; không diễn giải thành thành công.
Output của subprocess/native code chưa redirect qua Python không được Tee thu
thập; vẫn giữ log tmux và log project hiện có.

Audit dữ liệu chi tiết vẫn ở work directory: `project_status/*.json`,
`export_summary`, `exporter_tail`, `context_audit.json`, split audit và manifest.
Checkpoint/model, predictions và metrics thuộc `outputs/`, không đưa vào Git.
DeepSeek giữ checkpoint SQLite và cấu hình để từ chối resume sai dữ liệu/model.

Đây là refactor kiến trúc và vận hành, không đổi tập test, nhãn, ranking,
masking hay giới hạn candidate 8k. Việc đủ 3.277 mẫu v18 vẫn cần build và so
đối chiếu sau merge; không lấy số test pass thay cho kiểm chứng Dataset thật.

## Tài liệu và artifacts

Tài liệu sử dụng hiện hành ở README root và README của từng môi trường.
Các ghi chú rollout context v2/v3 và kế hoạch đã thay thế được bỏ khỏi cây làm
việc; lịch sử Git và bản stash trước merge giữ được nội dung cũ. Giữ lại
inventory/regression JSON, audit v18–v19, kết quả model và danh sách benchmark
đang được generator sử dụng. Không xóa Dataset, checkpoint hay credentials.
