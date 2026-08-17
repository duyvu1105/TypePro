# TypePro agent runbook

Các hướng dẫn này áp dụng cho toàn bộ repository. Nguồn chi tiết chính là
`kaggle_notebooks/README.md`; đọc file đó và
`kaggle_notebooks/shard_account_plan.json` trước khi thay đổi hoặc push workflow
Kaggle.

## An toàn credential

- Không đọc, in, paste hoặc đưa nội dung API key vào log, notebook, patch hay
  câu trả lời. Không mở `kaggle.json`/`kaggle2.json` chỉ để kiểm tra thủ công.
- `kaggle.json` và `kaggle2.json` ở root là credential local đã được `.gitignore`:
  mặc định lần lượt phải thuộc `duyvu1105` và `duymign`. Script push tự đọc và
  kiểm tra username; không tự xây lệnh shell làm lộ key.
- Nếu key xuất hiện trong chat/log/diff, coi như đã lộ: yêu cầu revoke và tạo
  key mới trước khi chạy job thật.
- Không commit credential, Dataset payload lớn, thư mục build hoặc output tạm.
- Push Kaggle là thay đổi trạng thái bên ngoài. Dry-run trước; chỉ dùng `--push`
  khi người dùng yêu cầu push/chạy thật.

## Hợp đồng workflow hiện tại

Không giả định “mỗi shard là một notebook”. Workflow hiện tại có hai template,
mỗi template được push thành năm Kaggle versions độc lập:

| Shards | Runner/Dataset owner | Kernel | Dataset visibility |
| --- | --- | --- | --- |
| `00-04` | `duyvu1105` | `duyvu1105/typepro-shards-00-04` | private |
| `05-09` | `duymign` | `duymign/typepro-shards-05-09` | public |

Final merge chạy dưới `duyvu1105` và tạo private Dataset
`duyvu1105/typepro-python-contrastive`. Shards `05-09` phải public để tài khoản
final đọc được; không đổi visibility/owner riêng lẻ nếu chưa cập nhật và kiểm
tra lại toàn bộ `shard_account_plan.json`.

Các file điều khiển:

- `kaggle_notebooks/generate_notebooks.py`: nguồn sinh notebook.
- `kaggle_notebooks/commit_shard_versions.py`: render/push đúng một shard cho
  mỗi version.
- `kaggle_notebooks/shard_account_plan.json`: mapping owner/kernel/shard.
- `kaggle_notebooks/03_merge_finalize.ipynb`: merge và publish final Dataset.
- `kaggle_notebooks/04_train_and_infer.ipynb`: train sau khi attach final Dataset.

Không sửa tay notebook sinh ra nếu thay đổi có thể biểu diễn trong generator.
Sửa `generate_notebooks.py`, sinh lại artifacts, rồi kiểm tra diff.

## Sinh và kiểm tra notebook

Sinh lại workflow chuẩn:

```bash
python kaggle_notebooks/generate_notebooks.py --shards 10 --runner-accounts duyvu1105 duymign --dataset-owner duyvu1105
```

Dry-run render đủ mười versions, không gọi Kaggle:

```bash
python kaggle_notebooks/commit_shard_versions.py
```

Trước khi push, kiểm tra output dry-run phải phủ shards `0..9` đúng một lần,
mỗi account đúng năm shard, owner và visibility khớp bảng trên. Chạy test liên
quan khi thay đổi generator/publisher:

```bash
python -m pytest codet5p_type_retrieval/tests -q -p no:cacheprovider
```

## Push notebook versions lên Kaggle

Lệnh chuẩn push cả mười jobs (năm versions cho mỗi account):

```bash
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_shard_versions.py --push
```

Mặc định script dùng `kaggle.json` cho `duyvu1105` và `kaggle2.json` cho
`duymign`, đồng thời xác minh credential thực sự thuộc đúng runner trước push.
Muốn dùng credential ở vị trí khác, truyền mapping tường minh:

```bash
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_shard_versions.py --credential "duyvu1105=D:\secure\duyvu.json" --credential "duymign=D:\secure\duymign.json" --push
```

Retry đúng một shard, không push lại cả batch:

```bash
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_shard_versions.py --shard 6 --push
```

Retry một số shard:

```bash
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/commit_shard_versions.py --shard 2 --shard 8 --push
```

`kaggle kernels push` vào kernel ID đã tồn tại sẽ tạo version mới và bắt đầu
run. Không xem việc CLI trả exit code `0` là đủ; script phải tiếp tục kiểm tra
các error marker trong output.

## Xác thực trong Kaggle notebook

Ưu tiên notebook chạy cùng account với Dataset owner. Có thể đặt Secrets cùng
account bằng `TYPEPRO_PUBLISH_USERNAME` + `TYPEPRO_PUBLISH_KEY`; fallback là
`KAGGLE_USERNAME` + `KAGGLE_KEY`. Merge dùng
`TYPEPRO_FINAL_USERNAME` + `TYPEPRO_FINAL_KEY` nếu cần override.

Workflow pin `kaggle==1.7.4.2` khi dùng legacy key để token/OAuth tự động của
Kaggle host không ghi đè owner. Luôn xác minh username hiệu lực trước publish.
Dataset ID phải có dạng `authenticated-owner/lowercase-slug`; không hard-code
một owner khác credential.

## Publish Dataset đúng cách

Không gọi `kaggle datasets create` trực tiếp cho shard/final trong workflow
thông thường. Dùng các publisher của repository; chúng kiểm tra metadata,
owner, create-vs-version, manifest và lỗi semantic dù CLI trả exit code `0`.

Publish lại một completed shard ngay trong Kaggle session:

```bash
python -u /kaggle/working/TypePro/codet5p_type_retrieval/publish_shard.py \
  --work-dir /kaggle/working/typepro_build_shard_06 \
  --payload-dir /kaggle/working/publish_shard_06 \
  --dataset-id duymign/typepro-build-shard-06 \
  --title "TypePro Python shard 06 of 10" \
  --message "Completed TypePro shard 06 of 10" \
  --expected-shard-index 6 \
  --expected-shard-count 10 \
  --public
```

Với shard `00-04`, thay owner/index tương ứng và bỏ `--public`. Publish final
Dataset chỉ sau verify/merge:

```bash
python -u /kaggle/working/TypePro/codet5p_type_retrieval/publish_kaggle.py \
  --data-dir /kaggle/working/typepro_python_contrastive \
  --dataset-id duyvu1105/typepro-python-contrastive \
  --title "TypePro Python Third-Party Contrastive Data" \
  --message "Merge 10 verified TypePro shards"
```

`third_party_kb` là build cache, không phải merge input và không được đóng vào
shard archive. Payload shard chỉ cần metadata, `raw_slices`, `project_status`,
`runtime_manifest.json` và `shard_manifest.json`; publisher phải từ chối path
collision không phân biệt hoa/thường.

## Kiểm tra kết quả trên Kaggle

- Xác nhận Dataset bằng exact owner listing và `kaggle datasets files
  owner/slug --page-size 10`.
- Không kết luận create thất bại chỉ vì `kaggle datasets status` trả HTTP 403:
  legacy status endpoint có thể 403 sau khi create thành công. Publisher đã có
  fallback sang file listing.
- Một Dataset private chỉ hiện với owner/collaborator. Mở URL bằng account khác
  có thể trông như không tồn tại.
- Chỉ coi shard sẵn sàng merge khi `shard_manifest.json` có đúng
  `shard_index`, `shard_count=10`, `missing_projects=[]`, và đủ các thư mục
  `metadata`, `raw_slices`, `project_status`.

## Resume và recovery

Chạy lại cùng shard notebook sẽ dùng Dataset/output hiện có khi tương thích và
bỏ qua project đã hoàn tất. Nếu publish thất bại nhưng Kaggle version vẫn còn
archive/completed work directory, tạo publish-only recovery notebook:

```bash
uv run --with kaggle==1.7.4.2 python kaggle_notebooks/recover_shard_version.py --source-version 8=9 --push
```

Trong ví dụ, shard `8` được lấy từ version `9`; phải thay bằng version thực tế.
Luôn dry-run bằng cách bỏ `--push` trước. Nếu `kaggle kernels output` của version
ERROR rỗng thì session đã đóng không recover được; retry đúng shard bằng
`commit_shard_versions.py --shard N --push`.

Các script `restore_shard_02_from_v8.py` và
`resume_shards_from_versions.py` chỉ dành cho lịch sử workflow năm shard. Output
có `shard_count=5` không được trộn với workflow mười shard hiện tại.

## Trình tự hoàn tất

1. Generate và dry-run mười versions.
2. Push hai nhóm versions bằng đúng credential runner.
3. Xác nhận datasets `00-04` dưới `duyvu1105` và `05-09` dưới `duymign`.
4. Chạy `03_merge_finalize.ipynb` dưới `duyvu1105`.
5. Verify final Dataset, attach nó vào `04_train_and_infer.ipynb`, rồi train GPU.
6. Báo rõ kernel/version/Dataset URL nào đã được tạo; không tuyên bố thành công
   nếu chưa có bằng chứng từ manifest hoặc file listing.
