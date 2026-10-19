# TypePro agent runbook

## Quy tắc Git: chỉ dùng nhánh main (2026-10-19)

- Chỉ làm việc, commit và push trên một nhánh duy nhất: `main`.
- Không tự tạo hoặc chuyển sang nhánh khác, kể cả nhánh tạm, nhánh sửa lỗi,
  nhánh tối ưu hoặc nhánh dùng riêng để chạy Kaggle. Không dùng worktree hay
  detached HEAD để lách quy tắc này.
- Các job Kaggle phải pin commit đã có trên `main`, không dùng commit chỉ có
  trên nhánh khác.
- Chỉ được dùng nhánh khác khi người dùng yêu cầu rõ ràng cho công việc đó.

## Current authorized workflow (2026-10-18)

The user authorized replacing the historical two-account workflow below with
21 independent physical jobs across three accounts. For current generate,
validate and scheduling commands, read `kaggle_notebooks/README.md` and
`kaggle_notebooks/shard_account_plan.json`.

- duyvu1105 (`kaggle.json`): logical shards 0, 1 part 1 (`1/30`), 2 (3 parts), 4, 5; private.
- duymign (`kaggle2.json`): shard 1 part 2 (`11/30`), logical shards 3 (3 parts), 6, 7 (2 parts); public.
- vdduy1105 (`kaggle3.json`): shard 1 part 3 (`21/30`), logical shards 8, 9 (5 parts); public.
- Physical jobs per account: 7/7/7, at most five active jobs per account.
- Shard 2 retains 2/20; old 12/20 is replaced by 12/40 and 32/40.
  New kernels use part-02-subpart-01/02; new Dataset slugs end in -of-40.
- Shard 1 replaces `1/10` with `1/30`, `11/30`, `21/30`, one part per account.
- Split parts use distinct kernels. Preserve all 21 physical coordinates in the
  plans, including shard 9's hierarchical /30 and /90 partitions.
- Final merge uses the exact 21 plan inputs and publishes privately as duyvu1105.
- Use `schedule_shards.py` for the complete rerun; dry-run before `--push`.
- Never read/print credential contents for inspection. Programs may load keys
  solely to authenticate and must validate the expected username.
- Edit generated notebooks through the generator. Run the full pipeline test
  suite before Git/Kaggle push. Do not commit datasets, credentials or temp outputs.
- Shared-KB schema v6 invalidates old raw slices; merge rejects legacy rows.
- Reuse one KB per project. Build it without return annotations; mask source
  before retrieval and target signatures in returned definition copies.
- Report actual kernel versions and statuses; submission is not dataset success.

The remainder preserves the historical runbook. Its two-account, ten-input
restrictions and commands are superseded by the current section and README;
its credential, publisher and verification safety rules still apply.


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

Workflow hiện tại có đúng mười notebook shard độc lập, một notebook cho mỗi
`SHARD_INDEX` từ `00` đến `09`; mỗi runner sở hữu năm notebook:

| Shards | Runner/Dataset owner | Kernel | Dataset visibility |
| --- | --- | --- | --- |
| `00-04` | `duyvu1105` | `duyvu1105/typepro-python-shard-XX` | private |
| `05-09` | `duymign` | `duymign/typepro-python-shard-XX` | public |

Mỗi logical shard chạy đúng một version với physical coordinate `index/10`.
Merge gắn đúng 10 Dataset inputs từ `shard_merge_plan.json`; không chia shard
thành các part `/20` hoặc `/30`.

Final merge chạy dưới `duyvu1105` và tạo private Dataset
`duyvu1105/typepro-python-generative`. Shards `05-09` phải public để tài khoản
final đọc được; không đổi visibility/owner riêng lẻ nếu chưa cập nhật và kiểm
tra lại toàn bộ `shard_account_plan.json`.

Các file điều khiển:

- `kaggle_notebooks/generate_notebooks.py`: nguồn sinh notebook.
- `kaggle_notebooks/commit_shard_versions.py`: validate/push đúng mười notebook.
- `kaggle_notebooks/shard_account_plan.json`: mapping owner/kernel/shard.
- `kaggle_notebooks/01_typepro_shard_00.ipynb` đến
  `10_typepro_shard_09.ipynb`: mười shard notebooks.
- `kaggle_notebooks/11_merge_finalize.ipynb`: merge và publish final Dataset.
- `kaggle_notebooks/12_train_and_infer.ipynb`: train sau khi attach final Dataset.

Không sửa tay notebook sinh ra nếu thay đổi có thể biểu diễn trong generator.
Sửa `generate_notebooks.py`, sinh lại artifacts, rồi kiểm tra diff.

## Sinh và kiểm tra notebook

Sinh lại workflow chuẩn:

```bash
python kaggle_notebooks/generate_notebooks.py --shards 10 --runner-accounts duyvu1105 duymign --dataset-owner duyvu1105
```

Dry-run validate/render đủ mười notebook, không gọi Kaggle:

```bash
python kaggle_notebooks/commit_shard_versions.py
```

Trước khi push, kiểm tra output dry-run phải phủ shards `0..9` đúng một lần,
mỗi account đúng năm shard, owner và visibility khớp bảng trên. Chạy test liên
quan khi thay đổi generator/publisher:

```bash
python -m pytest tests -q -p no:cacheprovider
```

## Push shard notebooks lên Kaggle

Lệnh chuẩn push cả mười jobs (năm notebook cho mỗi account):

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
python -u /kaggle/working/TypePro/typepro/publishing/shard.py \
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
python -u /kaggle/working/TypePro/typepro/publishing/final.py \
  --data-dir /kaggle/working/typepro_python_generative \
  --dataset-id duyvu1105/typepro-python-generative \
  --title "TypePro Python Generative Project-KB Data" \
  --message "Merge 10 verified TypePro shards"
```

`third_party_kb` cũ không phải merge input. Mỗi project phải có
`project_kb/<owner>__<repo>/knowledge_base.json` độc lập và file này phải được
đóng vào shard archive, merge, rồi giữ lại trong Dataset cuối. Payload shard
gồm metadata, `raw_slices`, `project_status`, `project_kb`,
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
  `metadata`, `raw_slices`, `project_status`, `project_kb`.

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

Các tiện ích recovery của workflow năm shard đã được loại bỏ sau refactor.
Dùng `recover_shard_version.py` hoặc scheduler theo plan 21 partition hiện tại.
Output có `shard_count=5` không được trộn với workflow hiện tại.

## Trình tự hoàn tất

1. Generate và dry-run mười notebook.
2. Push hai nhóm notebook bằng đúng credential runner.
3. Xác nhận datasets `00-04` dưới `duyvu1105` và `05-09` dưới `duymign`.
4. Chạy `11_merge_finalize.ipynb` dưới `duyvu1105`.
5. Verify final Dataset, attach nó vào `12_train_and_infer.ipynb`, rồi train GPU.
6. Báo rõ kernel/version/Dataset URL nào đã được tạo; không tuyên bố thành công
   nếu chưa có bằng chứng từ manifest hoặc file listing.
