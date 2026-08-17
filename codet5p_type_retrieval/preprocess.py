from __future__ import annotations

import argparse
import json
import os
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from data_utils import (
    canonical_type_name,
    deterministic_split,
    format_candidate,
    format_query,
    get_project,
    get_slice,
    json_preview,
    normalize_recommendations,
    iter_records,
    print_jsonl_samples,
)


SPLITS = ("train", "validation", "test")


def recommendation_coverage(stats: Counter) -> dict[str, dict[str, int | float]]:
    """Summarize whether each eligible sample's gold type was recommended."""
    coverage = {}
    for split in SPLITS:
        found = stats[f"{split}_gold_recommended"]
        missing = stats[f"{split}_gold_not_recommended"]
        total = found + missing
        coverage[split] = {
            "total_samples": total,
            "ground_truth_in_recommendation_types": found,
            "ground_truth_not_in_recommendation_types": missing,
            "percentage": round(100.0 * found / total, 2) if total else 0.0,
        }
    return coverage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert TypePro slices to contrastive CodeT5+ data")
    parser.add_argument("--input", nargs="+", required=True, help="TypePro JSON/JSONL outputs")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--label-field", default="gttype")
    parser.add_argument("--max-negatives", type=int, default=7)
    parser.add_argument("--min-negatives", type=int, default=1)
    parser.add_argument("--train-ratio", type=float, default=0.70)
    parser.add_argument("--validation-ratio", type=float, default=0.10)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--preview-samples", type=int, default=2, help="Samples printed per split; 0 disables previews")
    parser.add_argument("--preview-max-chars", type=int, default=1600, help="Maximum characters per preview; 0 prints all")
    parser.add_argument("--log-every", type=int, default=10000, help="Print streaming progress every N records; 0 disables")
    parser.add_argument(
        "--missing-positive", choices=("append", "drop"), default="drop",
        help="Training behavior when the recommender misses gold",
    )
    parser.add_argument(
        "--missing-positive-eval", choices=("append", "drop"), default="drop",
        help="Validation/test behavior; drop avoids injecting gold into evaluation candidates",
    )
    parser.add_argument(
        "--positive-policy", choices=("recommendation", "ground-truth"), default="recommendation",
        help="ground-truth always creates the positive from the label; recommendations remain negatives",
    )
    return parser.parse_args()


def source_split(record: dict[str, Any], project: str, args: argparse.Namespace) -> str:
    split = str(record.get("split") or "").lower()
    if split in {"train", "validation", "test"}:
        return split
    if split in {"valid", "val", "dev"}:
        return "validation"
    return deterministic_split(project, args.train_ratio, args.validation_ratio)


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)
    catalogs: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    stats = Counter()

    def records():
        for source in args.input:
            yield from iter_records(source)

    # Pass 1 keeps only the small recommendation catalog in memory. Raw slices
    # can be many gigabytes, so retaining staged queries would exhaust Kaggle RAM.
    for record in records():
        stats["input_records"] += 1
        code_slice = get_slice(record)
        label = str(record.get(args.label_field) or "").strip()
        if not code_slice or not label:
            stats["missing_slice_or_label"] += 1
            if args.log_every and stats["input_records"] % args.log_every == 0:
                print(
                    f"[preprocess:catalog] scanned={stats['input_records']:,} "
                    f"missing_slice_or_label={stats['missing_slice_or_label']:,}",
                    flush=True,
                )
            continue
        project = get_project(record)
        split = source_split(record, project, args)
        stats[f"{split}_eligible_input"] += 1
        recommendations = normalize_recommendations(record)
        for candidate in recommendations:
            catalogs[split].setdefault(canonical_type_name(candidate["name"]), candidate)
        if args.log_every and stats["input_records"] % args.log_every == 0:
            print(
                f"[preprocess:catalog] scanned={stats['input_records']:,} "
                f"missing_slice_or_label={stats['missing_slice_or_label']:,}",
                flush=True,
            )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary_paths = {split: output_dir / f"{split}.jsonl.tmp" for split in ("train", "validation", "test")}
    handles = {split: path.open("w", encoding="utf-8") for split, path in temporary_paths.items()}
    try:
        # Pass 2 creates pairs and streams them directly to the destination split.
        processed = 0
        previewed = Counter()
        for index, record in enumerate(records()):
            processed += 1
            if args.log_every and processed % args.log_every == 0:
                print(
                    "[preprocess:pairs] "
                    f"processed={processed:,} train={stats['train_written']:,} "
                    f"validation={stats['validation_written']:,} test={stats['test_written']:,}",
                    flush=True,
                )
            code_slice = get_slice(record)
            label = str(record.get(args.label_field) or "").strip()
            if not code_slice or not label:
                continue
            project = get_project(record)
            split = source_split(record, project, args)
            recommendations = normalize_recommendations(record)
            key = canonical_type_name(label)
            positive = next((item for item in recommendations if canonical_type_name(item["name"]) == key), None)
            gold_was_recommended = positive is not None
            if gold_was_recommended:
                stats[f"{split}_gold_recommended"] += 1
            else:
                stats[f"{split}_gold_not_recommended"] += 1
                if args.positive_policy == "recommendation":
                    missing_mode = args.missing_positive if split == "train" else args.missing_positive_eval
                    if missing_mode == "drop":
                        continue
            if args.positive_policy == "ground-truth" or positive is None:
                catalog_positive = positive or catalogs[split].get(key)
                positive = {
                    **(catalog_positive or {}),
                    "name": label,
                    "definition": (catalog_positive or {}).get("definition", label),
                    "source": "ground_truth",
                }

            negatives = [item for item in recommendations if canonical_type_name(item["name"]) != key]
            # TypePro recommendations are already ranked: retain the hardest ones first.
            negatives = negatives[: args.max_negatives]
            if len(negatives) < args.min_negatives:
                fallback = [item for other_key, item in catalogs[split].items() if other_key != key]
                rng.shuffle(fallback)
                existing = {canonical_type_name(item["name"]) for item in negatives}
                for item in fallback:
                    item_key = canonical_type_name(item["name"])
                    if item_key not in existing:
                        negatives.append(item)
                        existing.add(item_key)
                    if len(negatives) >= args.min_negatives:
                        break
            if not negatives:
                stats["no_negative"] += 1
                continue

            selected = [positive] + negatives[: args.max_negatives]
            row = {
                "id": str(record.get("id") or f"{project}:{record.get('file', '')}:{record.get('loc', index)}:{record.get('name', '')}"),
                "project": project,
                "split": split,
                "label": label,
                "query": format_query(record, code_slice),
                "metadata": {
                    "file": record.get("file") or record.get("path"),
                    "loc": record.get("loc"),
                    "scope": record.get("scope"),
                    "name": record.get("name"),
                    "source_commit": record.get("source_commit") or record.get("commit_hash"),
                },
                "candidates": [
                    {
                        "name": item["name"],
                        "text": format_candidate(item["name"], item["definition"]),
                        "is_positive": candidate_index == 0,
                        "source": (
                            "ground_truth" if candidate_index == 0
                            else str(item.get("source") or "recommendation_negative")
                        ),
                        **({"package": item["package"]} if item.get("package") else {}),
                        **({"qualified_name": item["qualified_name"]} if item.get("qualified_name") else {}),
                        **({"kind": item["kind"]} if item.get("kind") else {}),
                    }
                    for candidate_index, item in enumerate(selected)
                ],
            }
            handles[split].write(json.dumps(row, ensure_ascii=False) + "\n")
            stats[f"{split}_written"] += 1
            if previewed[split] < args.preview_samples:
                previewed[split] += 1
                print(
                    f"\n[preprocess:sample] {split} #{previewed[split]}\n"
                    f"{json_preview(row, args.preview_max_chars)}",
                    flush=True,
                )
    finally:
        for handle in handles.values():
            handle.close()

    for split, temporary in temporary_paths.items():
        os.replace(temporary, output_dir / f"{split}.jsonl")

    stats["usable_records"] = sum(stats[f"{split}_written"] for split in SPLITS)
    with (output_dir / "preprocess_stats.json").open("w", encoding="utf-8") as handle:
        json.dump(dict(stats), handle, indent=2, ensure_ascii=False)
    summary = {
        "input_records": stats["input_records"],
        "missing_slice_or_label": stats["missing_slice_or_label"],
        "no_negative": stats["no_negative"],
        "usable_records": stats["usable_records"],
        "splits": {
            split: {
                "eligible_input": stats[f"{split}_eligible_input"],
                "gold_recommended": stats[f"{split}_gold_recommended"],
                "gold_not_recommended": stats[f"{split}_gold_not_recommended"],
                "written": stats[f"{split}_written"],
            }
            for split in SPLITS
        },
        "recommendation_coverage": recommendation_coverage(stats),
    }
    print(f"\n[preprocess:final-counts]\n{json.dumps(summary, indent=2, ensure_ascii=False)}", flush=True)
    print("\n[ground-truth-in-recommendation-types]", flush=True)
    for split, values in summary["recommendation_coverage"].items():
        print(
            f"{split}: {values['ground_truth_in_recommendation_types']:,}/"
            f"{values['total_samples']:,} samples ({values['percentage']:.2f}%)",
            flush=True,
        )
    for split in SPLITS:
        print_jsonl_samples(
            output_dir / f"{split}.jsonl",
            args.preview_samples,
            args.preview_max_chars,
            title=f"processed {split}",
        )


if __name__ == "__main__":
    main()
