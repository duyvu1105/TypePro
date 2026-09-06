"""Create CodeT5 sequence-to-sequence records from project-local KB results."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


SPLITS = ("train", "validation", "test")


def iter_records(path: Path) -> Iterable[dict[str, Any]]:
    paths = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    for source in paths:
        with source.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


def project_name(row: dict[str, Any]) -> str:
    url = str(row.get("url") or "").rstrip("/")
    if url:
        parts = url.split("/")
        return "/".join(parts[-2:])
    path = str(row.get("file") or row.get("path") or "unknown").replace("\\", "/")
    parts = path.split("/")
    if "repos" in parts and len(parts) > parts.index("repos") + 2:
        index = parts.index("repos")
        return "/".join(parts[index + 1:index + 3])
    return parts[0]


def stable_split(project: str, train_ratio: float, validation_ratio: float) -> str:
    value = int(hashlib.sha256(project.encode()).hexdigest()[:16], 16) / 16**16
    if value < train_ratio:
        return "train"
    if value < train_ratio + validation_ratio:
        return "validation"
    return "test"


def normalized_recommendations(row: dict[str, Any], limit: int) -> list[dict[str, str]]:
    result = []
    seen = set()
    for item in row.get("recommendation_types") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("type") or "").strip()
        definition = str(item.get("definition") or "").strip()
        qualified = str(item.get("qualified_name") or name).strip()
        key = qualified.casefold()
        if not name or not definition or key in seen:
            continue
        seen.add(key)
        result.append({
            "type": name,
            "definition": definition,
            **({"qualified_name": qualified} if qualified else {}),
        })
        if len(result) >= limit:
            break
    return result


def target_function(row: dict[str, Any]) -> str:
    value = str(row.get("target_function") or row.get("loc") or "global")
    return value.split("@", 1)[0]


def target_scope(row: dict[str, Any]) -> str:
    """Normalize the target kind exposed to the language model."""
    value = str(row.get("scope") or row.get("target_scope") or "unknown").strip().casefold()
    aliases = {"parameter": "arg", "param": "arg", "argument": "arg"}
    return aliases.get(value, value or "unknown")


def format_input(
    name: str, function: str, scope: str, code_slice: str,
    recommendations: list[dict[str, str]],
) -> str:
    sections = [
        f"[TARGET_NAME] {name}",
        f"[TARGET_FUNCTION] {function}",
        f"[TARGET_SCOPE] {scope}",
        f"[INTERPROCEDURAL_SLICE]\n{code_slice}",
        "[RECOMMENDATION_TYPES]",
    ]
    for item in recommendations:
        sections.append(
            f"[TYPE] {item['type']}\n[DEFINITION]\n{item['definition']}"
        )
    return "\n".join(sections)


def record_fields(row: dict[str, Any], label_field: str = "gttype", limit: int = 10):
    """Shared eligibility check for project selection and actual sample writing."""
    return (
        str(row.get("name") or "").strip(),
        str(row.get(label_field) or "").strip(),
        str(row.get("interprocedural_slice") or "").strip(),
        normalized_recommendations(row, limit),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build TypePro generative CodeT5 data")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--label-field", default="gttype")
    parser.add_argument("--recommendation-limit", type=int, default=10)
    parser.add_argument("--train-ratio", type=float, default=0.70)
    parser.add_argument("--validation-ratio", type=float, default=0.10)
    parser.add_argument("--project-split-map", type=Path)
    args = parser.parse_args()
    if args.recommendation_limit != 10:
        parser.error("The dataset contract requires exactly a top-10 limit")

    output = Path(args.output_dir)
    split_map = json.loads(args.project_split_map.read_text(encoding="utf-8")) if args.project_split_map else None
    output.mkdir(parents=True, exist_ok=True)
    temporary = {split: output / f"{split}.jsonl.tmp" for split in SPLITS}
    handles = {split: path.open("w", encoding="utf-8") for split, path in temporary.items()}
    stats: Counter[str] = Counter()
    try:
        for index, row in enumerate(iter_records(Path(args.input))):
            stats["input_records"] += 1
            name, label, code_slice, recommendations = record_fields(row, args.label_field, args.recommendation_limit)
            if not name or not label or not code_slice or not recommendations:
                stats["dropped_incomplete"] += 1
                continue
            project = project_name(row)
            split = str(row.get("split") or "").casefold()
            if split_map is not None:
                split = split_map[project]
                if split not in SPLITS:
                    raise ValueError(f"Invalid split for project {project}: {split}")
            if split not in SPLITS:
                split = stable_split(project, args.train_ratio, args.validation_ratio)
            function = target_function(row)
            scope = target_scope(row)
            item = {
                "id": str(row.get("id") or f"{project}:{row.get('file', '')}:{index}:{name}"),
                "project": project,
                "split": split,
                "target_name": name,
                "target_function": function,
                "target_scope": scope,
                "interprocedural_slice": code_slice,
                "recommendation_types": recommendations,
                "input": format_input(name, function, scope, code_slice, recommendations),
                "label": label,
                "source_commit": row.get("source_commit"),
            }
            handles[split].write(json.dumps(item, ensure_ascii=False) + "\n")
            stats[f"{split}_written"] += 1
            stats["written"] += 1
    finally:
        for handle in handles.values():
            handle.close()
    for split, path in temporary.items():
        os.replace(path, output / f"{split}.jsonl")
    (output / "preprocess_stats.json").write_text(
        json.dumps(dict(stats), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(dict(stats), indent=2))


if __name__ == "__main__":
    main()
