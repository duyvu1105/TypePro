# Chạy TypePro trên một GPU Vast.ai

Notebook **không bắt buộc** trên Vast.ai. Có thể chạy pipeline hoàn toàn qua
SSH/tmux, nhưng notebook thuận tiện cho lần đầu vì chia rõ từng bước và hiển thị
GPU, kiểm tra Dataset, log train và kết quả inference.

Notebook sẵn dùng: `01_typepro_qwen25_1gpu.ipynb`. File này được sinh bởi
`generate_notebook.py`; hãy sửa generator rồi sinh lại thay vì sửa tay ipynb.

## Cấu hình máy khuyến nghị

- 1 GPU NVIDIA có ít nhất 24 GB VRAM (RTX 3090/4090, A5000, A6000 hoặc tương đương).
- On-demand cho lần chạy đầu; tránh interruptible khi chưa có cơ chế resume.
- 100 GB disk để có chỗ cho image, Dataset, Hugging Face cache và checkpoint.
  Vast.ai không cho tăng disk local sau khi tạo instance.
- Reliability cao (ưu tiên từ 98% trở lên), đủ system RAM, dung lượng tải xuống
  và băng thông phù hợp.
- Template PyTorch/CUDA được Vast.ai khuyến nghị, launch mode `Jupyter + SSH`.

Notebook mặc định train Qwen2.5-Coder-0.5B bằng QLoRA 4-bit trên 7.000 mẫu,
context 8.192 token, micro-batch 1 và gradient accumulation 16. Sau lần chạy
thử thành công, đặt `TRAIN_SAMPLES = None` để dùng toàn bộ tập train. Nếu CUDA
out-of-memory, giảm `INPUT_LENGTH` xuống 4096 trước.

## Bắt đầu từ con số 0

1. Tạo tài khoản tại Vast.ai, xác minh email, vào **Billing → Add Credit** và
   nạp tiền. Có thể bật cảnh báo số dư thấp.
2. Vào **Keys**, thêm SSH public key nếu muốn dùng terminal. Với Windows có thể
   tạo key bằng `ssh-keygen -t ed25519`; chỉ upload file `.pub`, không upload
   private key.
3. Vào **Templates**, chọn template PyTorch có `Jupyter + SSH`. Không đưa Kaggle
   token hoặc khóa bí mật vào template/environment công khai.
4. Vào **Search**, lọc `1 GPU`, VRAM từ 24 GB, reliability cao và chọn
   **on-demand**. Đặt disk 100 GB, kiểm tra tổng giá GPU + storage + bandwidth,
   rồi bấm **Rent**.
5. Chờ instance hiện nút **Open**. Mở Instance Portal rồi Jupyter. Direct HTTPS
   nhanh hơn nhưng có thể cần cài certificate của Vast.ai; proxy Jupyter dễ bắt
   đầu hơn.
6. Trong Jupyter, upload `01_typepro_qwen25_1gpu.ipynb` vào `/workspace`, mở
   notebook và chạy các cell theo thứ tự.
7. Khi cell Dataset hỏi token, dán **Kaggle API token** vào ô nhập ẩn. Dataset
   `duyvu1105/typepro-python-generative` là private nên tài khoản/token phải có
   quyền đọc. Notebook không ghi token vào file hoặc output.
8. Kiểm tra cell GPU báo đúng một GPU và cell verify Dataset trả
   `"verified": true`, sau đó mới chạy cell train.
9. Sau train, chạy inference và cell đóng gói. Tải file
   `/workspace/outputs/typepro_vastai_result.tar.gz` về máy hoặc sao chép sang
   cloud storage.
10. Khi đã có bản sao kết quả, **Stop** chỉ dừng phí GPU nhưng vẫn tính phí
    storage. **Destroy/Delete** mới xóa instance và dừng toàn bộ phí; dữ liệu
    local sẽ mất sau khi xóa.

## Chạy bền hơn qua SSH/tmux

Jupyter phù hợp để thiết lập và kiểm tra. Với một job dài, mở lệnh SSH do Vast.ai
cung cấp, chạy `tmux new -s typepro`, rồi chạy chính lệnh `accelerate launch`
được notebook in ra. Nhấn `Ctrl-b`, sau đó `d` để detach; quay lại bằng
`tmux attach -t typepro`. Cách này giữ tiến trình độc lập với cửa sổ terminal.

## Tài liệu Vast.ai chính thức

- Quickstart: https://docs.vast.ai/guides/get-started/quickstart
- Chọn và thuê instance: https://docs.vast.ai/guides/instances/choosing/find-and-rent
- Kết nối Jupyter: https://docs.vast.ai/guides/instances/connect/jupyter
- Di chuyển dữ liệu: https://docs.vast.ai/guides/instances/storage/data-movement
