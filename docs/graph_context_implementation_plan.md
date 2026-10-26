# Kế hoạch triển khai context dựa trên đồ thị cho toàn bộ TypePro

Trạng thái: thiết kế triển khai, chưa chạy thực nghiệm. Đây là pipeline mới áp dụng
cho mọi target arg/return; v24 là baseline thực nghiệm. Không chọn sample bằng gold,
prediction hoặc danh sách lỗi đã xem, không trả context v24 khi graph gặp khó.

Chiến lược Git theo yêu cầu người dùng: khôi phục nền v24 trên `main`, sau đó tạo
nhánh `experiment/graph-context-v1` từ commit baseline đã kiểm tra. Toàn bộ graph
được triển khai/thử nghiệm trên nhánh này. Đây là ngoại lệ được người dùng yêu cầu
rõ ràng đối với quy tắc chỉ dùng main trong AGENTS.md, giới hạn cho công việc này.
Tài liệu này là kế hoạch; việc sửa tài liệu chưa thực hiện rollback hoặc tạo nhánh.

## 1. Phạm vi và hợp đồng đầu ra

- `main`: nền slicing/retrieval v24, không chứa implementation graph thử nghiệm.
- `experiment/graph-context-v1`: toàn bộ implementation, tests, exporter và
  generator thay đổi cho graph; áp dụng graph cho mọi target của lần chạy nhánh này.
- Khôi phục main bằng commit mới có diff được kiểm tra, không reset/rewrite lịch sử.
  Phạm vi khôi phục và các sửa lỗi độc lập cần giữ được chốt trong M0 bên dưới.
- Dùng source gốc ở project revision lock, không dựng graph từ slice v24/v26 vì
  slice đã có thể mất dữ liệu. Khóa cả phiên bản dependency KB dùng để so sánh.
- Tái sử dụng hạ tầng scan/import/catalog/masking đã kiểm tra; thay việc chọn
  slice và candidate bằng policy mới `graph-context-v1`.
- Mọi target đủ điều kiện đều đi qua mask → graph view → resolve → select → render.
- Mỗi target có một outcome: ready, unresolved, budget_exceeded, parse_error,
  target_not_found hoặc timeout. Không silently drop sample hoặc đổi policy.
- `unresolved` có thể có prompt hợp lệ, nhưng phải ghi rõ phạm vi chưa phân giải
  trong audit. Không diễn giải nó là graph đã chứng minh đầy đủ ngữ nghĩa.
- Mỗi output ghi stable target identity, source hash/commit, graph/context/budget
  policy versions, tokenizer/template fingerprint, selected evidence và gaps.
- Graph không dự đoán gold type; nó chọn và trình bày bằng chứng lấy từ source.

## M0 — Khôi phục main về nền v24 và tạo nhánh thử nghiệm

### A. Chốt trạng thái và phạm vi rollback

1. Ghi SHA hiện tại của main và kiểm tra working tree. Bảo toàn thay đổi đang có,
   đặc biệt tài liệu kế hoạch; không dùng reset --hard, clean hoặc ghi đè file người
   dùng đang sửa. Lịch sử trước rollback vẫn giữ các commit v26 để tham khảo.
2. Mốc code v24 là `a498310a55833428e67e63f3c94b8b9a8a33ed92`, theo
   `outputs/qwen25-coder-05b-v24-6k-2ep/launch_config.json`; đối chiếu với manifest
   dataset v24 trước khi sửa. Đây là mốc source, không phải tên nhánh hay Dataset ID.
3. Review diff từ mốc này đến main, lập danh sách restore/retain theo hành vi:
   - Restore thuật toán slicing/context v24 (`ast-context-v7-verified-signature-evidence`)
     và retrieval/ranking/rendering tương ứng, gồm thay đổi liên quan trong
     `ast_context_slicer.py`, `slicing_code_class.py`, `export_slices.py`,
     `candidate_policy.py`, `project_kb.py` và các helper thực sự ảnh hưởng output.
   - Đồng bộ tests, config, schema/cache validity, verify/merge và notebook generator
     với baseline; không chỉ đổi chuỗi POLICY trong khi vẫn chạy reducer v26.
   - Giữ các sửa lỗi độc lập: bảo vệ credential/masking, greedy decoding, sửa lỗi
     exporter/publisher và vận hành plan 21 jobs. Mỗi phần giữ phải có lý do và
     kiểm tra không vô tình đưa lại policy cắt v26. Nếu thay đổi ảnh hưởng output,
     ghi rõ trong baseline manifest thay vì gọi nó là bản v24 byte-for-byte.
   - Không đưa các cải tiến mới như graph hay chat packing mới vào commit rollback.
     Không ghi đè datasets, checkpoint và predictions đã lưu.
4. Main sau bước này là **baseline thuật toán v24 + các sửa lỗi độc lập được liệt kê**,
   không phải toàn bộ cây file giống hệt commit lịch sử v24. Các artifact v24 lưu
   sẵn vẫn là đối chứng lịch sử nguyên bản để phân biệt hai khái niệm này.

### B. Kiểm chứng main và tạo nhánh

5. Chạy regression tests cho hành vi slicing/retrieval v24, smoke export trên source
   và dependency KB đã khóa, kiểm tra masking và schema. So output với artifact
   v24 trên target chung; điều tra khác biệt, không yêu cầu tái tạo lỗi timeout cũ.
6. Chạy full suite `python -m pytest tests -q -p no:cacheprovider`, generate notebooks
   qua generator và dry-run validation theo README. Ghi kết quả vào baseline report.
7. Tạo commit rollback mới trên main sau khi checks đạt; ghi SHA làm `baseline_sha`.
8. Tạo `experiment/graph-context-v1` từ đúng `baseline_sha`. Nếu nhánh cùng tên đã
   tồn tại, kiểm tra ancestry và thay đổi trước khi tái sử dụng; không force-reset.
9. Triển khai M1–M7 chỉ trên nhánh thử nghiệm. Main giữ vai trò baseline; các sửa lỗi
   dùng chung phát sinh sau này phải được review riêng và ghi lại baseline version.

### C. Quy tắc kết thúc thử nghiệm

- Kết quả chưa đạt: giữ code/report ở nhánh thử nghiệm, main tiếp tục dùng baseline.
- Kết quả đạt: chuẩn bị diff/PR cùng validation, coverage và resource report để
  xem xét tích hợp. Không tự merge graph vào main chỉ vì implementation đã hoàn tất.
- Push Git/Kaggle, chạy batch hoặc train là bước triển khai riêng khi được yêu cầu;
  yêu cầu sửa plan hiện tại không được diễn giải là lệnh khởi chạy những bước đó.

## 2. M1 — Hợp đồng dữ liệu, masking và benchmark cố định

File tích hợp: `analysis/export_slices.py`, `analysis/target_context.py`,
`data/prepare.py`, `data/verify.py`, `data/merge.py`.

1. Khóa target roster của train/validation/test theo v24; nhận diện bằng project,
   source file, qualified function, scope, target, cùng disambiguator cho definition
   trùng. Không ghép chỉ theo số dòng ID của bản export.
2. Tạo `TargetSpec` không có gold label. Truyền labels riêng tới evaluator/trainer.
3. Tạo masked source view trước mọi truy vấn target-specific. Mask các bản sao
   target trong candidate, re-export và chữ ký có thể tham gia quyết định selection.
4. Shared KB vẫn một bản/project và không dùng return annotations để xây/retrieve.
   Shared structural graph không có cạnh suy ra từ annotation. Chỉ target view
   được bổ sung evidence annotation được phép từ source đã mask. Không đưa target
   annotation hoặc kết quả dẫn xuất từ nó vào cache dùng chung.
5. Non-target source signatures đang được phép sử dụng là evidence có provenance;
   chúng không được biến thành kênh đưa target return annotation trở lại shared KB.
6. Đặt cache key theo source/dependency/schema/masking/target-view versions. Token
   budget cache còn phải gồm tokenizer và chat template fingerprint.

Hoàn tất khi thay gold label hoặc thay annotation target bằng các kiểu khác không
làm thay đổi nội dung/policy lựa chọn sau masking; chạy cả cache cold/warm và đảo
thứ tự xử lý target. So sánh semantic content, không so số byte offset bị dịch.

## 3. M2 — Graph trong từng hàm

Module mới dự kiến:

- `analysis/evidence_graph.py`: schema node/edge/provenance và serialization.
- `analysis/graph_builder.py`: CFG, reaching definitions, def-use, control edges.

Node gồm symbol, binding/lần định nghĩa, operation/call, field access, container
element, condition, return/yield, annotation/alias evidence và unresolved region.
Node có scope, source location, source hash và stable ID. Cùng tên biến trong hai
scope hoặc hai lần gán là hai binding khác nhau.

Edges tối thiểu:

| Edge | Ý nghĩa |
| --- | --- |
| def_use / assign | Giá trị dùng đến từ định nghĩa nào |
| merge | Hợp các định nghĩa có thể tới điểm dùng |
| control | Điều kiện/nhánh chi phối câu lệnh |
| return / yield | Giá trị đi đến target return |
| field_read / field_write | Đọc/ghi member với receiver xác định |
| element / unpack | Quan hệ container, phần tử và vị trí unpack |
| argument / call_result | Liên kết callsite với input/output callable |
| annotation / alias | Bằng chứng khai báo từ source view được phép |

Xử lý if/else, loops, break/continue, implicit None, early returns, try/except/
finally, with, await, yield/yield-from, comprehension, closure và shadowing.
Tính reaching definitions đến fixed point với các vòng lặp, không dùng biến cùng
tên như thể chỉ có một giá trị. Mutation/alias chưa chứng minh được dùng may-edge,
không gộp thành quan hệ chắc chắn.

Tạo test tổng quát cho reassignment, hai nhánh khác kiểu, return trong finally,
mutation qua alias và nested scopes. Kiểm tra edges/source spans dự kiến và các
bằng chứng cần giữ; không chỉ snapshot toàn bộ output của implementation.

## 4. M3 — Graph liên hàm, field, alias và fixture

Module mới: `analysis/graph_resolver.py`, `analysis/graph_contracts.py`.
Tái sử dụng/tách phần catalog độc lập từ `ast_context_slicer.FunctionCatalog`,
`project_index.py`, `signature_contracts.py`; không gọi reducer v7/v9 để chọn code.

- Phân giải bằng scope, import, qualified name, re-export và receiver type evidence.
  Tên gần giống chỉ được xem là candidate giả thuyết, không tạo resolved edge.
- Bind positional/keyword/default/self/cls. Không đoán expansion *args/**kwargs.
- Nối argument → formal parameter và return summary → call result theo callsite,
  tránh trộn caller không liên quan. Giữ đa nghiệm khi có nhiều binding hợp lệ.
- Theo field tới owner class, base class/property/constructor có provenance.
  Alias mở rộng có cycle detection, đồng thời giữ nguyên tên alias cho rendering.
- Fixture resolver xét tên, conftest/module scope, explicit name, override,
  parametrize và plugin provenance; không tìm fixture chỉ bằng tên toàn project.
- Thêm bảng contract phiên bản hóa cho builtins như map, zip, enumerate, iter,
  container construction, append/extend và await/yield. Chỉ áp dụng khi xác định
  callable là builtin tương ứng, không áp dụng nếu bị shadow hoặc monkey-patch.
- Contract thư viện dựa vào chữ ký/implementation đã xác minh trong dependency KB
  hoặc source cùng phiên bản; không viết quy tắc riêng cho tên sample/dataset.
- Tính function summaries, xử lý recursion bằng SCC/fixed point. Giới hạn mở rộng
  theo config; chạm giới hạn phải tạo gap, không giả vờ đã đóng dependency.

Quan hệ động chưa xác định tạo `unresolved` node với source span, possible bindings
và lý do. Selector giữ vùng source chứa thao tác và các phụ thuộc nhìn thấy; nếu
không khoanh được ảnh hưởng, giữ thân scope đó như một evidence group. Đây là cùng
graph policy cho mọi sample, không dùng lại context được xuất bởi v24.

Hoàn tất khi các fixture tổng quát bao phủ argument binding, constructor-field,
property/inheritance, alias cycles, callback/map, scope shadowing và dynamic calls;
resolved edge nào cũng có rule/provenance để truy lại được.

## 5. M4 — Chọn evidence và retrieval cho tất cả target

Module mới: `analysis/graph_selection.py`, `analysis/graph_render.py`.
Tích hợp với `candidate_policy.py`, `project_kb.py` và `export_slices.py`.

1. Arg target: seed đối số, các lần sử dụng/ghi lại, caller được phân giải và các
   quan hệ type evidence nối tới chúng. Return target: seed mọi đường return/yield,
   gồm implicit None và control conditions liên quan.
2. Truy vấn định nghĩa bằng graph/symbol trên source đầy đủ đã mask, trước khi
   rút gọn. Không query retrieval từ code đã cắt rồi mới cố tìm lại evidence mất.
3. Tạo evidence groups: một claim/constraint + source statements + đường nối nó
   với target. Group có prerequisites; không chọn field annotation đơn lẻ mất owner.
4. Giữ target header, seed operations và các control/definition links bắt buộc.
   Bổ sung context/support groups theo priority deterministic:
   direct verified contract → field/alias support → verified callers/fixtures →
   evidence gián tiếp → lexical hypotheses. Trong cùng mức ưu tiên: evidence mới,
   khoảng cách phụ thuộc, token cost, stable ID. Chưa dùng trọng số công thức tự đề
   xuất ở cuộc thảo luận trước; có thể nghiên cứu scoring sau khi baseline chạy được.
5. Dedupe theo canonical source/symbol/span, không gộp class chỉ vì trùng short name.
   Chỉ lấy member/signature/body statements liên quan của một class. Loại membership
   trùng, không loại hai bằng chứng có nội dung mâu thuẫn; ghi conflict cho audit.
6. Không ép đủ 10 candidate. Candidate giả thuyết không được thay resolved evidence
   hoặc dùng làm bằng chứng để cắt những dependency chưa xác định.
7. Render lại code theo source order, kèm module/owner đủ phân biệt symbol; giữ các
   wrapper điều khiển cần thiết. Không viết annotation suy đoán vào code và không
   biểu diễn một scope bị lược như thể đó là source thực thi nguyên bản.

Audit cho mỗi target: node/edge IDs, source spans, resolved/unresolved counts,
retained/omitted group IDs, lý do chọn/bỏ, conflicts và token counts. Diagnostics
chi tiết đặt ngoài prompt; model nhận code/signatures và source identity hữu ích.

## 6. M5 — Token budget và chat format thống nhất

Module mới `shared/context_packing.py`; sửa `shared/generative_chat.py`,
`training/generative.py`, `inference/generative.py` và length-cache fingerprint.

- Với cấu hình 6144/64, ngân sách toàn prompt là 6080 token; phải trừ system,
  target headers và chat delimiters theo tokenizer/template thật trước khi pack.
- Pack evidence groups cùng prerequisites; cost là marginal cost sau dedup.
  Kiểm tra lại số token của toàn prompt sau mỗi kết quả render cuối.
- Dựng chat bằng API template, không cắt `chat_token_ids(... )[:6080]` nữa.
- Train collator, train length measurement, inference và preview dùng một hàm
  dựng prompt. Chọn context không được phụ thuộc độ dài gold completion.
- Test assistant boundary/EOS/label masking, batching, Unicode, prompt dài,
  completion budget và parity train/infer.

Nếu phần bắt buộc lớn hơn budget: outcome `budget_exceeded`, lưu evidence đầy đủ
và token requirement. Không xóa lén mandatory group và không quay sang v24.
Một nguồn budget hữu hạn không thể đảm bảo giữ mọi semantic dependency của mọi
Python program. Nếu case này còn nhiều, thay chính sách group/budget trên validation
và áp dụng lại toàn bộ tập; không tăng budget riêng dựa trên prediction sai.

## 7. M6 — Tích hợp dataset, cache và full export

- Đổi policy/schema stamps đồng bộ ở prepare/export/verify/merge/publish để old
  raw slices không được reuse. Graph cache phải có schema riêng và source locks.
- Reuse một KB/project khi schema thực sự tương thích; nếu cần thêm member/source
  metadata thì bump KB schema và rebuild, không ghi stamp mới lên KB cũ.
- Shared graph gồm topology/structural summaries; target overlay thêm mask và
  evidence riêng. Không dựng lại toàn project cho từng sample. Bound memory và
  disk caches; record build/query/render time và peak resource metrics.
- Có file outcome ledger cho toàn roster, kể cả failed/overbudget. Dataset release
  không được tự đổi split hoặc drop target để làm đẹp coverage/accuracy.
- Mọi row được xuất có graph-context-v1; merge từ chối mixed policy, mismatched
  source/dependency/tokenizer fingerprint. Giữ nguyên gold và provenance.

Tích hợp notebooks qua generator trên nhánh thử nghiệm. Khi chạy Kaggle ở bước
được yêu cầu sau này:

- Production/baseline jobs vẫn pin commit trên main.
- Graph experiment phải pin đúng full SHA đã kiểm tra và được publish từ
  `experiment/graph-context-v1`, không để scheduler mặc định resolve GitHub main.
  Kiểm tra generator/scheduler/revision validation có hỗ trợ branch thử nghiệm;
  nếu cần, thêm cấu hình explicit cho experiment, không đổi mặc định production.
- Dùng experiment profile với kernel/Dataset slugs, output directory và scheduler
  state riêng. Không push kernel graph vào ID của jobs baseline hoặc ghi đè Dataset
  baseline. Final experiment Dataset cũng riêng và private dưới duyvu1105.
- Giữ 21 physical coordinates, 7/7/7, visibility và giới hạn 5 active/account của
  plan hiện hành; tính cả job ngoài experiment khi kiểm tra slot. Experiment merge
  dùng đúng 21 Dataset IDs của experiment profile, không trộn dữ liệu production.
- Dry-run scheduler và chạy full tests trước push. Xác minh actual kernel versions,
  Dataset manifests và policy stamps của toàn bộ merge inputs.

Việc lập kế hoạch này không khởi chạy/push job hoặc train mới.

## 8. M7 — Kiểm chứng và điều kiện chấp nhận

### Kiểm chứng kỹ thuật bắt buộc

- Mọi target trong roster có outcome; không có legacy fallback trong graph path.
- Không gold/target-annotation leakage trong selection, rendering hoặc cache.
- Không broken evidence paths, incorrect identity merges, missing chat boundary
  hoặc silent token truncation ở prompt ready.
- Test synthetic và project fixtures độc lập với các sample test đã audit. Những
  sample test đã xem là development-known examples, không dùng làm holdout mới.
- Full test suite: `python -m pytest tests -q -p no:cacheprovider`.

### So sánh model

1. Giữ một checkpoint, greedy, tokenizer/template, budget và batch size cố định.
   So v24 input + chat packing sửa đúng với graph input + cùng packing. Chạy thêm
   v24 raw inference cũ riêng để đo tác động boundary, không gộp nó vào lợi ích graph.
   Harness đối chứng chạy trên nhánh experiment bằng artifact v24 đã khóa hoặc
   baseline export ghi `baseline_sha`; không sửa main để chạy ablation. Report ghi
   cả baseline SHA, experiment SHA và hash input của mỗi variant.
2. Chia validation theo project thành phần phát triển và phần xác nhận; freeze
   config trước phần xác nhận. Nếu validation đã bị xem/tune, ghi hạn chế và dùng
   project holdout mới nếu đủ dữ liệu. Test hiện tại đã được xem sâu nên không gọi
   là holdout hoàn toàn độc lập cho thiết kế này.
3. Ablation: graph đầy đủ evidence trong cùng budget; thêm chọn member; thêm loại
   redundancy/noise. Áp dụng mỗi variant cho toàn roster validation, không chọn
   variant tốt nhất riêng cho từng sample.
4. Báo EM gốc, fixes/regressions, unresolved/overbudget/failure coverage, tokens
   median/p95, runtime/memory và theo arg/return/project. Lỗi hệ thống tính riêng
   và tính sai trong metric end-to-end trên roster cố định; báo thêm common-ready
   metric nhưng không dùng nó che việc mất sample.
5. Với EM, dùng paired comparison và bootstrap theo project để phản ánh các mẫu
   cùng project có tương quan; chốt trước mục tiêu: tăng EM, hoặc giảm token trong
   biên non-inferiority được đặt trước khi xem kết quả. Không tự chọn ngưỡng sau khi
   xem score. Kết quả chưa rõ thì báo inconclusive.
6. Khi correctness/coverage đạt, train đối chứng v24-context vs graph-context trên
   cùng train target roster, source/dependency locks, model/hyperparameters/seeds,
   sample ordering policy và safe chat packing. Cùng seed không bảo đảm cùng batch
   order nếu length grouping phụ thuộc context; kiểm soát hoặc báo rõ yếu tố này.
   Dùng ít nhất 3 seed nếu tài nguyên cho phép, không tuyên bố ổn định từ một run.
7. Đánh giá ma trận 2×2 train-context/eval-context trên validation để phân biệt
   ảnh hưởng prompt và adaptation. Chỉ chạy final test sau khi freeze thiết kế.

Nếu graph không cải thiện, kết quả là phương pháp chưa đạt mục tiêu; điều chỉnh
thuật toán chung hoặc giữ nó ở trạng thái thử nghiệm. Không chọn quay về v24 cho
từng sample để che regression của graph.

## 9. Các đợt triển khai theo phụ thuộc

| Đợt | Công việc | Đầu ra để review |
| --- | --- | --- |
| 0 | M0 trên main, rồi tách nhánh | Rollback diff, tests, baseline_sha, experiment branch |
| 1 | M1 + schema M2 | TargetSpec, graph types, fixed roster, masking tests |
| 2 | M2 + M3 | Builder/resolver/contracts, evidence provenance, synthetic tests |
| 3 | M4 + M5 | Một đường graph-select-render-pack cho mọi target, budget tests |
| 4 | M6 | Full outcome ledger, versioned exports, verify/merge compatibility |
| 5 | M7 | Validation/ablation report, resource profile, quyết định train |
| 6 | Train/full experiment run khi được yêu cầu | Seed results, manifests, actual statuses |

Đợt 1–6 cho graph thực hiện trên `experiment/graph-context-v1`. Production rollout
chỉ lập sau khi review kết quả và quyết định tích hợp; không đồng nhất experiment
full run với production rollout.

Tiêu chí “áp dụng cho tất cả” là cùng graph policy và cùng quy tắc xử lý uncertainty
cho mọi sample. Nó không có nghĩa mọi dependency đều phân giải được hoặc mọi prompt
đều giữ đủ source trong 6080 token; các giới hạn đó phải được đo và công bố.
