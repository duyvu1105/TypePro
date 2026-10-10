# Kiểm tra và triển khai context v2 — 2026-10-10

Người dùng đã cho phép triển khai plan, kiểm tra, push Git và chạy lại **15 physical job đầu tiên, 5 job mỗi account**. Bốn job còn lại chờ yêu cầu tiếp tục. Không tự merge hoặc train.

## Hành vi đã sửa

- Target vẫn cắt theo AST; giữ compound statement và fallback nguyên target khi tác động chưa phân tích chắc được.
- Chỉ chèn callee sau khi resolve một hàm độc lập đúng module hoặc import project tường minh, không bị che tên. Tên ngắn trùng nhau không cho phép chèn definition.
- Biết đúng callee nhưng chưa bind chắc đối số (`*args`, `**kwargs`, variadic...) hoặc reducer chưa chắc thì giữ nguyên đúng hàm đó. Chỉ mở rộng một hop.
- Caller context phải resolve call site về đúng target bằng AST catalog. Không tin kết quả unique-leaf của index cũ; không tìm mọi biến cùng tên trên toàn file và không mở rộng tiếp callee của caller.
- Class đoán theo tên chỉ cung cấp bằng chứng retrieval. Slice giữ header class bao quanh target theo AST, không chép mọi method của class.
- Candidate class chọn method/thuộc tính và phụ thuộc cần thiết, giữ thân method tại bước chọn. Sau masking/member selection, **mọi candidate definition áp dụng `[:16000]`**, tối đa 10 candidate; KB vẫn đầy đủ. Preprocess chặn lại trước ghép input.
- Schema retrieval v11, masking v7 và context v2 làm raw slices cũ mất tương thích. Merge từ chối trộn policy cũ và definition vượt giới hạn.
- Publisher chạy audit trên toàn bộ raw rows trước đóng gói: policy, số candidate, độ dài definition và provenance của callee. Lỗi dừng publish; `context_audit.json` lưu median/p95/p99/max theo ký tự và 20 mẫu lớn nhất.

## Rà soát các đường dễ sai

Đã kiểm tra local assignment, parameter shadowing, local import, nested function, exception binding, import có điều kiện, tên chỉ có ở module khác, relative import, alias import, receiver chưa biết, monkeypatch và dynamic scope. Thiếu caller scope, lambda/nested callable hoặc mutation tường minh làm resolver từ chối chèn thân.

Resolver hiện hỗ trợ hàm độc lập trong module và project import. Method trên receiver, kể cả `self`/`cls`, vẫn được xử lý bảo thủ là chưa resolve; không dùng annotation để đoán receiver. Đây là giới hạn coverage có chủ đích, không phải khẳng định mọi lời gọi Python đều giải được. Audit kiểm tra hợp đồng output/provenance; không phải chứng minh mọi tác động runtime Python.

Các test chống leak sẵn có tiếp tục chạy: thay annotation target nhưng giữ code/KB thì slice và candidate bất biến; không dùng return annotation làm seed KB; không sửa shared KB tại chỗ. Test mới còn kiểm tra candidate Unicode ở 15.999/16.000/16.001/430.474 ký tự, ranking qua bước cap và publisher từ chối raw vượt trần.

## Đo lại hai project gây phình

Replay cùng metadata tại source commit đã khóa, so sánh AST v1 (`9610ee4`) với bản sửa. Dùng KB từ source project, không thêm KB thư viện tùy chọn. Đây là bốn mẫu hồi quy, **không phải thống kê toàn Dataset**. Đơn vị là ký tự Unicode của input đầy đủ sau ghép tag/candidate; không suy ra token bằng tỷ lệ.

| Project / target | Input trước | Input sau | Slice sau | Candidate dài nhất sau |
| --- | ---: | ---: | ---: | ---: |
| SDK / `HttpAdapter.match`, param `request` | 1.298.803 | 14.925 | 546 | 4.536 |
| SDK / `HttpAdapter.match`, return | 1.304.041 | 32.815 | 535 | 4.921 |
| SQL / `_get_partition_data`, return | 440.223 | 6.830 | 801 | 4.617 |
| SQL / `_get_partition_data`, param `watermarks` | 49.121 | 42.218 | 801 | 16.000 |

SDK: cả hai mẫu trước có 2.316 definition `serialize` và 2.319 `deserialize` trong slice; sau sửa đều bằng **0**. SQL: trước có candidate `SqlBaseParser` 430.474 ký tự; slice mới thay đổi bằng chứng retrieval nên parser không còn trong top-10 mẫu return. Test độc lập vẫn xác nhận fallback definition 430.474 chỉ render 16.000, KB nguyên vẹn. Không quy toàn bộ giảm độ dài SQL cho riêng thao tác cap.

- SDK source: `929268c7649b1d6d3eca62778f30829387ee192f`.
- SQL source: `194ae1d0f9fb81998a0e31efe6936fe94d721a0c`.
- Test stress riêng tạo 2.400 class cùng có `serialize`/`deserialize`: không definition nào bị kéo vào slice khi receiver chưa rõ.

Không có tổng ngân sách candidate mới: 10 definition có thể cộng tới 160.000 ký tự. Target/hàm đã resolve thực sự dài vẫn được giữ và báo cáo. Vì vậy không cam kết mọi input vừa context model; shard không chạy tokenizer.

## Kiểm tra trước push

- `python -m pytest codet5p_type_retrieval/tests -q -p no:cacheprovider`: **203 passed, 2 skipped** (test phụ thuộc POSIX trên Windows).
- Sinh notebook qua generator; dry-run `commit_shard_versions.py`: **19 job**, phân bổ **7/6/6**, giữ nguyên tọa độ và visibility.
- `git diff --check`: kiểm tra trước commit.
- Scheduler đợt này dùng full Git SHA đã push, ledger mới và `--jobs-per-account 5`; dry-run phải có đúng **15 job, 5/5/5**.

## Đợt Kaggle được phép

| Account | Tọa độ được chạy |
| --- | --- |
| duyvu1105 | 0/10, 1/10, 2/20, 12/40, 32/40 |
| duymign | 3/30, 13/30, 23/30, 6/10, 7/20 |
| vdduy1105 | 8/10, 9/30, 19/30, 29/90, 59/90 |

Chờ tiếp: **4/10, 5/10, 17/20, 89/90**. Kernel version/status thực tế sẽ ghi vào báo cáo triển khai sau khi push; nhận submission chưa chứng minh Dataset hoàn thành.

Các thay đổi publisher final/republish đã có trong workspace từ lượt trước được kiểm tra cùng suite; đợt này không chạy final republish hoặc merge.

## Phát hiện khi xác minh Kaggle

Partition 2/20 v12 dừng trước slicing: Dataset cũ liệt kê được nhưng download trả HTTP 404. Sửa generator để bước resume tùy chọn khi download thất bại thì build mới; chỉ retry riêng 2/20. Không thay thuật toán context hoặc schema giữa đợt đầu và retry. Thêm test thực thi cell resume với listing thành công/download thất bại. Sau sửa: **204 passed, 2 skipped**; notebook sinh lại qua generator, dry-run riêng 2/20 trước push.
