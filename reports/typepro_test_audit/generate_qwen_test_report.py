#!/usr/bin/env python3
"""Regenerate the Qwen test audit from the cleaned v15 test artifacts."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "datasets/typepro-python-generative-v15/test.jsonl"
PREDICTION_PATH = ROOT / "outputs/qwen25-coder-05b-8192/test_predictions.jsonl"
REPORT_PATH = ROOT / "reports/typepro_test_audit/qwen25-coder-05b-8192-2e-4-test-report.md"

BASIC_TYPES = {
    "any", "asynciterable", "asynciterator", "awaitable", "bool", "bytearray",
    "bytes", "callable", "collection", "complex", "dict", "float", "frozenset",
    "generator", "int", "iterable", "iterator", "list", "mapping", "memoryview",
    "mutablemapping", "none", "nonetype", "object", "range", "sequence", "set",
    "str", "tuple", "type",
}

EXAMPLE_IDS = {
    "correct": [
        "opethe1st/MyJson:repos/opethe1st/MyJson/src/myjson/loading/node_from_tokens.py:43756:is_scalar",
        "kelsos/test-environment-scripts:repos/kelsos/test-environment-scripts/raiden_api/model/data.py:35181:state",
        "shunkakinoki/leetcode:repos/shunkakinoki/leetcode/src/1.two-sum.py:49976:nums",
        "jwnwilson/python_types:repos/jwnwilson/python_types/main.py:34778:user_mapping",
        "RacingTadpole/python-workshop:repos/RacingTadpole/python-workshop/python_workshop/types/t01_functions.py:9050:keys",
    ],
    "incorrect": [
        "opethe1st/MyJson:repos/opethe1st/MyJson/src/myjson/loading/node_from_tokens.py:43755:tokens",
        "be9/mypy-problem:repos/be9/mypy-problem/planner/scheduling/make_schedule.py:18871:make_schedule",
        "kelsos/test-environment-scripts:repos/kelsos/test-environment-scripts/raiden_api/model/data.py:35177:channel_identifier",
        "jasperges/pose-thumbnails:repos/jasperges/pose-thumbnails/pose_thumbnails/flip.py:33631:values",
        "JamesHageman/leetcode:repos/JamesHageman/leetcode/336.py:5667:words",
    ],
    "user_correct": [
        "flexiooss/flexio-flow:repos/flexiooss/flexio-flow/src/PoomCiDependency/FullRepository.py:28352:repository",
        "povilasb/httpmeter:repos/povilasb/httpmeter/httpmeter/stats.py:45277:summary",
        "aio-libs/aiozipkin:repos/aio-libs/aiozipkin/tests/conftest.py:12746:request",
        "Pylons/pyramid_openapi3:repos/Pylons/pyramid_openapi3/pyramid_openapi3/__init__.py:8904:config",
        "danielhfrank/dawg:repos/danielhfrank/dawg/dawg/pushover.py:23552:client_session",
    ],
    "user_incorrect": [
        "jwnwilson/python_types:repos/jwnwilson/python_types/main.py:34775:input_list",
        "MGodgildieva/allennlp_NLP_hw4:repos/MGodgildieva/allennlp_NLP_hw4/library/predictor/predictor.py:6750:predict_json",
        "umutseven92/LaFontaine:repos/umutseven92/LaFontaine/lafontaine/generator/video_generator.py:51017:_generate_from_scene",
        "ekisu/dots:repos/ekisu/dots/dots/cli.py:26259:output_args",
        "zulip/zulip:repos/zulip/zulip/zerver/migrations/0247_realmauditlog_event_type_to_int.py:51778:schema_editor",
    ],
}


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def pct(correct: int, total: int) -> str:
    return f"{correct / total * 100:.2f}%" if total else "0.00%"


def outer_type(label: str) -> str:
    match = re.match(r"\s*([A-Za-z_][\w.]*)", label or "")
    return match.group(1).split(".")[-1].lower() if match else ""


def is_basic(label: str) -> bool:
    return outer_type(label) in BASIC_TYPES


def example_block(number: int, row: dict, prediction: dict, kind: str) -> str:
    correct = bool(prediction["exact_match"])
    if kind.startswith("user_"):
        prefix = "Kiểu user-defined — đúng" if correct else "Kiểu user-defined — sai"
    else:
        prefix = "Đúng" if correct else "Sai"
    if correct:
        heading = f"{prefix} {number}: `{row['target_name']}` → `{prediction['label']}`"
    else:
        heading = (
            f"{prefix} {number}: nhãn `{prediction['label']}`, "
            f"model dự đoán `{prediction['prediction']}`"
        )
    normalized = prediction.get("normalized_prediction")
    normalized_text = "`null`" if normalized is None else f"`{normalized}`"
    return "\n".join([
        f"### {heading}",
        "",
        f"- ID: `{row['id']}`",
        f"- Project: `{row['project']}`",
        f"- Hàm đích: `{row['target_function']}`",
        f"- Phạm vi: `{row['target_scope']}`",
        f"- Nhãn: `{prediction['label']}`",
        f"- Dự đoán thô: `{prediction['prediction']}`",
        f"- Dự đoán chuẩn hóa: {normalized_text}",
        f"- Kết quả: **{'đúng' if correct else 'sai'}** "
        f"(`exact_match={str(correct).lower()}`, "
        f"`raw_exact_match={str(bool(prediction['raw_exact_match'])).lower()}`)",
        "",
        "Input đầy đủ từ Dataset v15:",
        "",
        "```text",
        row["input"].rstrip(),
        "```",
    ])


def validate(rows: list[dict], predictions: list[dict]) -> tuple[dict, dict]:
    row_by_id = {row["id"]: row for row in rows}
    pred_by_id = {item["id"]: item for item in predictions}
    if len(row_by_id) != len(rows) or len(pred_by_id) != len(predictions):
        raise ValueError("Duplicate row or prediction IDs")
    if set(row_by_id) != set(pred_by_id):
        raise ValueError("Dataset and prediction IDs do not match")
    for category, ids in EXAMPLE_IDS.items():
        for sample_id in ids:
            row = row_by_id[sample_id]
            pred = pred_by_id[sample_id]
            expected = category in {"correct", "user_correct"}
            if bool(pred["exact_match"]) != expected:
                raise ValueError(f"Unexpected example outcome: {sample_id}")
            expected_user = category.startswith("user_")
            if (not is_basic(pred["label"])) != expected_user:
                raise ValueError(f"Unexpected example type group: {sample_id}")
            recommendations = row["recommendation_types"]
            rendered = [(item["type"], item["definition"]) for item in recommendations]
            if len(rendered) != len(set(rendered)):
                raise ValueError(f"Example still has repeated rendered candidates: {sample_id}")
    return row_by_id, pred_by_id


def build_report(rows: list[dict], predictions: list[dict]) -> str:
    row_by_id, pred_by_id = validate(rows, predictions)
    total = len(rows)
    correct = sum(bool(pred_by_id[row["id"]]["exact_match"]) for row in rows)
    raw_correct = sum(bool(pred_by_id[row["id"]]["raw_exact_match"]) for row in rows)
    label_count = len({pred_by_id[row["id"]]["label"] for row in rows})
    invalid = sum(pred_by_id[row["id"]].get("normalized_prediction") is None for row in rows)
    empty = sum(pred_by_id[row["id"]].get("normalized_prediction") == "" for row in rows)
    qualified_duplicates = 0
    for row in rows:
        keys = [item.get("qualified_name", "").casefold() for item in row["recommendation_types"]]
        qualified_duplicates += len(keys) - len(set(keys))

    lines = [
        "# Báo cáo dự đoán kiểu dữ liệu trên tập test v15 đã làm sạch",
        "",
        "## Phạm vi và cách tính",
        "",
        "- Tập test: `datasets/typepro-python-generative-v15/test.jsonl`.",
        "- Kết quả model: `outputs/qwen25-coder-05b-8192/test_predictions.jsonl`.",
        f"- Số mẫu: **{total:,}**; số nhãn kiểu dữ liệu khác nhau: **{label_count:,}**.",
        "- Hai file được ghép theo `id`; không có ID trùng, thiếu hoặc dư.",
        "- Một dự đoán đúng khi `exact_match=true`, tức `normalized_prediction` bằng nhãn đã chuẩn hóa.",
        "",
        "## Kiểm tra dữ liệu recommendation đã làm sạch",
        "",
        "Mỗi mẫu v15 chứa 10 recommendation. Việc khử trùng dùng `qualified_name` làm khóa: "
        "alias cùng định danh bị loại, còn các type trùng tên nhưng thuộc module/package khác vẫn là các ứng viên riêng.",
        "",
        f"- Số `qualified_name` trùng trong cùng một mẫu: **{qualified_duplicates}**.",
        "- 20 ví dụ bên dưới được chọn từ v15 và không có cặp `[TYPE]`/`[DEFINITION]` trùng nhau trong block hiển thị.",
        "- ID có thể khác report cũ vì v15 được dựng lại từ dữ liệu đã làm sạch.",
        "",
        "## Kết quả tổng quan",
        "",
        "| Chỉ số | Đúng | Tổng | Tỷ lệ |",
        "| --- | ---: | ---: | ---: |",
        f"| Exact match sau chuẩn hóa | {correct:,} | {total:,} | {pct(correct, total)} |",
        f"| Exact match chuỗi thô | {raw_correct:,} | {total:,} | {pct(raw_correct, total)} |",
        f"| Sai sau chuẩn hóa | {total - correct:,} | {total:,} | {pct(total - correct, total)} |",
        "",
        f"Có **{invalid}** dự đoán không chuẩn hóa được và **{empty}** dự đoán rỗng. "
        f"Bước chuẩn hóa làm tăng đúng **{correct - raw_correct}** mẫu so với so sánh chuỗi thô.",
        "",
        "### Theo vị trí cần dự đoán",
        "",
        "| Phạm vi | Đúng | Tổng | Tỷ lệ đúng |",
        "| --- | ---: | ---: | ---: |",
    ]
    for scope in ("arg", "return"):
        scope_rows = [row for row in rows if row["target_scope"] == scope]
        scope_correct = sum(pred_by_id[row["id"]]["exact_match"] for row in scope_rows)
        lines.append(f"| `{scope}` | {scope_correct:,} | {len(scope_rows):,} | {pct(scope_correct, len(scope_rows))} |")

    section_titles = {
        "correct": "5 ví dụ dự đoán đúng",
        "incorrect": "5 ví dụ dự đoán sai",
        "user_correct": "5 ví dụ đúng với kiểu user-defined/named",
        "user_incorrect": "5 ví dụ sai với kiểu user-defined/named",
    }
    for category in ("correct", "incorrect", "user_correct", "user_incorrect"):
        lines.extend(["", f"## {section_titles[category]}", ""])
        for number, sample_id in enumerate(EXAMPLE_IDS[category], 1):
            lines.extend([
                example_block(number, row_by_id[sample_id], pred_by_id[sample_id], category),
                "",
            ])

    groups = {True: [], False: []}
    for row in rows:
        groups[is_basic(pred_by_id[row["id"]]["label"])].append(row)
    lines.extend([
        "## Độ chính xác theo nhóm kiểu dữ liệu",
        "",
        "### Quy tắc phân loại",
        "",
        "- Lấy kiểu ngoài cùng của annotation: `Dict[str, Any]` → `dict`, `List[Claim]` → `list`.",
        "- **Cơ bản/typing** gồm built-in và các container/protocol phổ biến của `typing`.",
        "- **User-defined/named** gồm các nhãn có kiểu ngoài cùng không thuộc nhóm trên. Nhóm này có thể gồm class từ standard library hoặc thư viện bên thứ ba.",
        "- `List[Claim]` được tính vào `list` vì việc phân nhóm dựa trên kiểu ngoài cùng.",
        "",
        "### So sánh hai nhóm",
        "",
        "| Nhóm | Đúng | Tổng | Tỷ lệ đúng | Số nhãn chính xác khác nhau |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    group_stats = {}
    for basic, title in ((True, "Cơ bản/typing"), (False, "User-defined/named")):
        group_rows = groups[basic]
        group_correct = sum(pred_by_id[row["id"]]["exact_match"] for row in group_rows)
        group_labels = {pred_by_id[row["id"]]["label"] for row in group_rows}
        group_stats[basic] = (group_correct, len(group_rows), len(group_labels))
        lines.append(
            f"| {title} | {group_correct:,} | {len(group_rows):,} | {pct(group_correct, len(group_rows))} | {len(group_labels):,} |"
        )
    lines.extend([
        f"| **Toàn bộ** | **{correct:,}** | **{total:,}** | **{pct(correct, total)}** | **{label_count:,}** |",
        "",
        "### Chi tiết các kiểu cơ bản/typing",
        "",
        "Các annotation có cùng kiểu ngoài cùng được gộp vào một dòng. Cột ví dụ hiển thị tối đa ba nhãn phổ biến.",
        "",
        "| Kiểu ngoài cùng | Ví dụ nhãn | Đúng | Tổng | Tỷ lệ đúng |",
        "| --- | --- | ---: | ---: | ---: |",
    ])
    by_outer = {}
    for row in groups[True]:
        pred = pred_by_id[row["id"]]
        by_outer.setdefault(outer_type(pred["label"]), []).append(pred)
    for name, items in sorted(by_outer.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        item_correct = sum(item["exact_match"] for item in items)
        labels = [label for label, _ in Counter(item["label"] for item in items).most_common(3)]
        examples = ", ".join(f"`{label}`" for label in labels)
        lines.append(f"| `{name}` | {examples} | {item_correct:,} | {len(items):,} | {pct(item_correct, len(items))} |")

    named_correct, named_total, named_labels = group_stats[False]
    lines.extend([
        "",
        "### Các kiểu user-defined/named phổ biến nhất",
        "",
        f"Toàn bộ nhóm có **{named_correct:,}/{named_total:,} mẫu đúng ({pct(named_correct, named_total)})** "
        f"trên **{named_labels:,} nhãn**. Bảng hiển thị 20 nhãn có nhiều mẫu nhất.",
        "",
        "| Kiểu dữ liệu | Đúng | Tổng | Tỷ lệ đúng |",
        "| --- | ---: | ---: | ---: |",
    ])
    named_by_label = {}
    for row in groups[False]:
        pred = pred_by_id[row["id"]]
        named_by_label.setdefault(pred["label"], []).append(pred)
    for label, items in sorted(named_by_label.items(), key=lambda pair: (-len(pair[1]), pair[0]))[:20]:
        item_correct = sum(item["exact_match"] for item in items)
        lines.append(f"| `{label}` | {item_correct:,} | {len(items):,} | {pct(item_correct, len(items))} |")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    rows = read_jsonl(DATA_PATH)
    predictions = read_jsonl(PREDICTION_PATH)
    REPORT_PATH.write_text(build_report(rows, predictions), encoding="utf-8")
    print(f"Wrote {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
