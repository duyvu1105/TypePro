# Fine-tune CodeT5+ với TypePro context và contrastive learning

Pipeline này là một **candidate retriever/ranker**, không phải decoder sinh type tự do:

1. Query encoder nhận `INTERPROCEDURAL_SLICE` cùng target name/kind.
2. Candidate encoder nhận tên và structural definition của từng recommendation type.
3. Hai nhánh dùng chung encoder `Salesforce/codet5p-220m`.
4. Cross-entropy trên cosine similarity/temperature chính là grouped InfoNCE: gold type là positive, các recommendation type còn lại là hard negatives.
5. Khi infer, type có cosine similarity cao nhất được chọn.

## Chạy toàn bộ pipeline một lần trên Kaggle

Pipeline được tách thành hai notebook:

- **Notebook A — build dataset một lần:** tải TypeGen, chia project, clone từng repository, chạy TypePro slicing, tạo pairs và publish `train/validation/test.jsonl` thành Kaggle Dataset.
- **Notebook B — fine-tune nhiều lần:** chỉ attach Kaggle Dataset đã xử lý; không download source repository và không chạy slicer lại.

### Notebook A: build và lưu dataset

Tạo Kaggle Notebook, bật **Internet**. CPU là đủ cho bước slicing; không cần dùng quota GPU. Add source code này dưới dạng Kaggle Dataset hoặc clone fork đã chứa các file mới, rồi xác định thư mục code:

```python
from pathlib import Path

# Nếu add source code bằng nút Add Input, sửa glob theo slug của bạn.
TYPEPRO_ROOT = next(Path("/kaggle/input").glob("*/TypePro"), None)
if TYPEPRO_ROOT is None:
    TYPEPRO_ROOT = Path("/kaggle/working/TypePro")  # dùng khi git clone vào working
print(TYPEPRO_ROOT)
```

Kaggle Inputs là read-only. Nếu code được add bằng **Add Input**, copy nó sang working trước khi chạy slicer:

```python
import shutil
from pathlib import Path

source = TYPEPRO_ROOT
target = Path("/kaggle/working/TypePro")
if source.resolve() != target.resolve() and not target.exists():
    shutil.copytree(source, target)
TYPEPRO_ROOT = target
```

Nếu dùng GitHub thay vì Add Input:

```bash
git clone https://github.com/<USER>/<FORK_CO_CODE_MOI>.git /kaggle/working/TypePro
```

Cài dependency builder:

```bash
cd /kaggle/working/TypePro/codet5p_type_retrieval
pip install -q -r requirements-build.txt
```

Chạy toàn bộ. Builder tự tải đúng `data.zip` của TypeGen và kiểm tra SHA-256:

```bash
python prepare_dataset.py \
  --stage all \
  --typepro-root /kaggle/working/TypePro \
  --work-dir /kaggle/working/typepro_build \
  --output-dir /kaggle/working/typepro_contrastive_dataset \
  --split-profile paper_project \
  --test-projects 100 \
  --validation-project-ratio 0.10 \
  --max-negatives 7 \
  --build-import-kb \
  --download-missing-imports \
  --preview-samples 2 \
  --preview-max-chars 1600 \
  --log-every 10000 \
  --seed 13
```

Trong log, `metadata:full-counts` in số annotation/project ngay sau khi chia tập;
`slice:progress` in tiến độ clone và số slice; `preprocess:final-counts` và
`dataset:full-counts` in đầy đủ số record thực tế sau filtering. Mặc định mỗi
split in 2 sample. Dùng `--preview-max-chars 0` để in nguyên nội dung sample,
hoặc `--preview-samples 0` để tắt preview.

`paper_project` bảo đảm train/validation/test không trùng project. Validation được lấy bên trong 70% train projects; test gồm 100 projects thuộc phần 30% còn lại. Có thể chạy theo từng stage để dễ resume:

```bash
python prepare_dataset.py --stage metadata --typepro-root /kaggle/working/TypePro
python prepare_dataset.py --stage slice    --typepro-root /kaggle/working/TypePro
python prepare_dataset.py --stage finalize --typepro-root /kaggle/working/TypePro
```

Mỗi project hoàn tất tạo một shard trong `typepro_build/raw_slices` và status trong `project_status`. Nếu cell bị dừng nhưng `/kaggle/working` vẫn còn, chạy lại `--stage slice`; project hoàn tất sẽ được bỏ qua. `--stage finalize` từ chối đóng gói khi còn project chưa được thử. Repository đã được thử nhưng bị xóa/private được ghi trong `manifest.json` và không chặn finalize; thêm `--strict-projects` nếu muốn bắt buộc không có lỗi nào.

Toàn bộ corpus có hàng nghìn repository và có thể vượt thời lượng một Kaggle session. Khi đó, tạo N notebook build giống nhau và đổi `shard-index` từ `0` đến `N-1`:

```bash
# Ví dụ notebook shard 3/5
python prepare_dataset.py --stage metadata \
  --split-profile paper_project --test-projects 100 --seed 13

python prepare_dataset.py --stage slice \
  --split-profile paper_project --test-projects 100 --seed 13 \
  --shard-count 5 --shard-index 3 \
  --build-import-kb --download-missing-imports
```

Save output `typepro_build` của mỗi notebook thành một Kaggle Dataset. Trong notebook merge, attach tất cả shard datasets rồi chạy:

```bash
python merge_shards.py \
  --shard-build-dirs /kaggle/input/typepro-build-shard-* \
  --work-dir /kaggle/working/typepro_build

python prepare_dataset.py --stage finalize \
  --work-dir /kaggle/working/typepro_build \
  --output-dir /kaggle/working/typepro_contrastive_dataset \
  --split-profile paper_project --test-projects 100 --seed 13
```

Merge kiểm tra manifest và checksum, do đó không thể vô tình trộn shard được tạo bằng seed/split khác nhau.

Để test nhanh trước khi chạy toàn bộ:

```bash
python prepare_dataset.py --stage slice --max-projects 5 --typepro-root /kaggle/working/TypePro
```

Không dùng `--max-projects` khi build dataset chính thức. Nếu có knowledge base JSON của top pip packages theo schema TypePro, add nó làm Kaggle Input và truyền:

```bash
--third-party-kb /kaggle/input/typepro-python-knowledge-base/dataset
```

Kiểm tra dataset sau khi finalize:

```bash
python verify_dataset.py --data-dir /kaggle/working/typepro_contrastive_dataset
```

Publish bằng Kaggle API. Tạo hai Kaggle Secrets `KAGGLE_USERNAME` và `KAGGLE_KEY`, rồi chạy một cell Python:

```python
import os
from kaggle_secrets import UserSecretsClient

secrets = UserSecretsClient()
os.environ["KAGGLE_USERNAME"] = secrets.get_secret("KAGGLE_USERNAME")
os.environ["KAGGLE_KEY"] = secrets.get_secret("KAGGLE_KEY")
```

```bash
python publish_kaggle.py \
  --data-dir /kaggle/working/typepro_contrastive_dataset \
  --dataset-id <KAGGLE_USERNAME>/typepro-codet5p-contrastive
```

Lần đầu script tạo private Dataset; những lần chạy sau tạo version mới. Bạn cũng có thể Commit Notebook, sau đó chọn **Create Dataset** từ notebook output.

### Notebook B: chỉ load dataset và fine-tune

Tạo notebook mới, bật GPU, Add Input dataset `typepro-codet5p-contrastive` vừa tạo. Không chạy `prepare_dataset.py` trong notebook này.

```bash
cd /kaggle/working/TypePro/codet5p_type_retrieval
pip install -q -r requirements.txt

python verify_dataset.py \
  --data-dir /kaggle/input/typepro-codet5p-contrastive

python train.py \
  --data-dir /kaggle/input/typepro-codet5p-contrastive \
  --output-dir /kaggle/working/codet5p-typepro \
  --model-name Salesforce/codet5p-220m-py \
  --batch-size 2 \
  --gradient-accumulation-steps 8 \
  --query-length 768 \
  --candidate-length 256 \
  --epochs 3 \
  --learning-rate 2e-5 \
  --mixed-precision fp16 \
  --gradient-checkpointing \
  --preview-samples 2 \
  --preview-max-chars 1600
```

Trước khi tải model, `train.py` quét ba file JSONL và in số train/validation/test,
tổng số record, kích thước file cùng các sample đầu tiên. Sau khi tải model,
script cũng in chính xác tổng số tham số được dùng và số tham số trainable.

Từ lần fine-tune thứ hai, chỉ thay hyperparameters và `--output-dir`; dataset input giữ nguyên.

### Giới hạn dữ liệu công khai

TypeGen release công khai không chứa `commit_hash`; builder ghi SHA thực tế của HEAD đã clone vào từng record và manifest. TypePro cũng không phát hành knowledge base top 5.000 pip packages trong repository hiện tại. Builder này thay thế bằng KB theo nhu cầu: đọc imports của từng project, quét `.py`/`.pyi` đã cài hoặc wheel tải về mà không import/thực thi package, rồi lưu class name, qualified name, bases, fields và public method signatures. Dataset chỉ giữ function parameters không phải built-in; positive luôn là `gttype`, recommendation types còn lại là negatives.

## 1. Dữ liệu

Paper TypePro dùng:

- Python: **ManyTypes4Py**, tải raw dataset từ [Zenodo](https://zenodo.org/records/5244636), hoặc lấy bộ đã xử lý theo TypeGen từ [TypeGen data release](https://github.com/JohnnyPeng18/TypeGen/releases/tag/data). TypePro chia theo project 70/30; paper dùng 226,767 train annotations và lấy 100 test projects (11,029 mẫu) để đánh giá.
- TypeScript: **ManyTypes4TypeScript** trên [Hugging Face](https://huggingface.co/datasets/kevinjesse/ManyTypes4TypeScript); paper lấy 10% train partition (260,767 mẫu) và 100 test projects (30,805 mẫu).

README TypePro hiện trỏ đúng tới ManyTypes4TypeScript nhưng hyperlink “released resources” cho Python đang rỗng. Vì vậy, với Python nên bắt đầu từ TypeGen data release (đúng schema mà TypePro kế thừa), còn Zenodo là nguồn raw/canonical.

Dataset annotation chưa đủ để train pipeline này. TypePro slicer cần source repository đúng commit để dựng inter-procedural information, và recommendation cần knowledge base class/interface. Vì vậy cần tạo record có dạng:

```json
{
  "url": "https://github.com/org/repo",
  "file": "path/to/file.py",
  "loc": "function@global",
  "scope": "arg",
  "name": "model",
  "gttype": "Ggnn",
  "code_slicing": "def f(model: <mask>): ...",
  "recommendation_types": [
    {"name": "Ggnn", "definition": "class Ggnn: ..."},
    {"name": "OtherModel", "definition": "class OtherModel: ..."}
  ]
}
```

Bạn có thể dùng trực tiếp output từ TypePro. Preprocessor hỗ trợ các field `code_slicing`/`slicedCode`, `type_recommend`/`typeRecommended`/`recommendation_types`, và có thể tách recommendation definitions từ `total_prompt`/`totalPrompt` cũ. Tuy nhiên `RQ Results` trong repo là **test output**, không dùng nó làm training data.

Để tạo train output đúng chuẩn:

- tải annotation và clone các repository ở đúng commit;
- chạy `Python/run_read_data.py <repo>` hoặc `TypeScript/Scripts/run.py <repo>` để dựng index inter-procedural;
- gọi slicer tương ứng như README gốc và lưu `slicing result` cùng `get_type_recommend()` (Python) hoặc `SlicedData.typeRecommended` (TypeScript), không cần gọi API LLM;
- giữ split theo **project**, tuyệt đối không random theo annotation/file để tránh cùng repository xuất hiện ở train và test.

Repo này có sẵn exporter offline cho Python (chạy từ thư mục `Python` để các path tương đối của TypePro đúng):

```bash
cd Python
python export_slices.py \
  --dataset /kaggle/input/manytypes4py/processed_train.json \
  --repos-root /kaggle/input/manytypes4py-repositories \
  --output /kaggle/working/typepro_train_slices.jsonl \
  --rebuild-index \
  --parameters-only \
  --exclude-builtins
```

`--rebuild-index` chạy `run_read_data.py` một lần cho mỗi project. Exporter không import/call OpenAI. Với TypeScript, dùng `TSSlicer.Slicing(...)` như `TypeScript/Test.ts` và lưu cả `ans.code` lẫn `ans.typeRecommended`; preprocessor bên dưới đọc được cùng schema.

## 2. Preprocess

Trong Kaggle, add JSON/JSONL đã xuất từ TypePro làm Input rồi chạy:

```bash
python preprocess.py \
  --input /kaggle/input/typepro-slices/train.json /kaggle/input/typepro-slices/test.json \
  --output-dir /kaggle/working/typepro_pairs \
  --label-field gttype \
  --max-negatives 7 \
  --positive-policy ground-truth \
  --preview-samples 2 \
  --preview-max-chars 1600 \
  --log-every 10000
```

Nếu record đã có `split`, script giữ nguyên. Nếu chưa có, script chia deterministically theo project. Recommendation list vốn đã được TypePro sắp theo structural similarity nên các item sai đầu danh sách là hard negatives tốt.

Với dataset parameter-only mới, dùng `--positive-policy ground-truth`: candidate đầu tiên luôn là `gttype`; nếu KB có structural definition tương ứng thì tái sử dụng definition đó, nếu không thì dùng name-only. Các recommendation khác là hard negatives. Chế độ cũ `--positive-policy recommendation` vẫn hỗ trợ `--missing-positive drop|append` cho ablation candidate-recall. File `preprocess_stats.json` vẫn ghi `*_gold_recommended` để đo khả năng KB tự tìm thấy gold, nhưng metric trên processed test là supervised ranking vì gold đã được đưa vào candidate set.

## 3. Train trên Kaggle

Khuyến nghị accelerator GPU T4/P100; bật Internet cho lần đầu tải model, hoặc add model checkpoint làm Kaggle Dataset.

```bash
pip install -q -r requirements.txt

python train.py \
  --data-dir /kaggle/working/typepro_pairs \
  --output-dir /kaggle/working/codet5p-typepro \
  --model-name Salesforce/codet5p-220m-py \
  --batch-size 2 \
  --gradient-accumulation-steps 8 \
  --query-length 768 \
  --candidate-length 256 \
  --epochs 3 \
  --learning-rate 2e-5 \
  --mixed-precision fp16 \
  --gradient-checkpointing \
  --preview-samples 2 \
  --preview-max-chars 1600
```

Nếu T4 bị OOM, giảm `--batch-size 2` hoặc `--query-length 384`. Checkpoint tốt nhất nằm trong `codet5p-typepro/best`.

## 4. Infer

`infer.py` đọc trực tiếp `test.jsonl` đã preprocess hoặc raw TypePro records. Nếu
input có label, script tự tính Top-1, MRR, candidate recall và end-to-end metric:

```bash
python infer.py \
  --checkpoint /kaggle/working/codet5p-typepro/best \
  --input /kaggle/input/typepro-codet5p-contrastive/test.jsonl \
  --output /kaggle/working/predictions.jsonl \
  --query-length 768 \
  --candidate-length 256 \
  --batch-size 4 \
  --top-k 5 \
  --preview-samples 3
```

Mỗi output chứa `prediction`, gold label, gold rank và ranking cosine similarity.
Với processed test, script đọc thêm `preprocess_stats.json` cùng thư mục để tính
end-to-end metric trên cả những mẫu bị loại vì gold không nằm trong candidates.

## Ghi chú thực nghiệm

- Paper gốc TypePro không fine-tune LLM theo cơ chế này; đây là phần mở rộng contrastive bi-encoder theo yêu cầu.
- Structural definition (fields + public methods) quan trọng hơn chỉ đưa tên type; nó bám sát Equation 1 của paper.
- Nên báo đồng thời candidate recall@K, conditional top-1 (trên các mẫu gold có trong candidates), và end-to-end top-1.
- Checkpoint 220M phù hợp Kaggle hơn 770M. TypeScript không nằm trong chín ngôn ngữ pretrain được nêu ở model card của checkpoint 220M, nên cần đánh giá riêng Python/TypeScript thay vì trộn rồi chỉ báo một con số.
