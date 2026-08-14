from __future__ import annotations

import argparse
import json
import os
from itertools import islice
from pathlib import Path
from typing import Any, Iterable, Iterator

import torch

from data_utils import (
    canonical_type_name,
    format_candidate,
    format_query,
    get_slice,
    iter_records,
    json_preview,
    normalize_recommendations,
)
from model import CodeT5pBiEncoder


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rank TypePro recommendation types by CodeT5+ similarity")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--input", required=True, help="Processed contrastive JSONL or raw TypePro JSON/JSONL")
    parser.add_argument("--output", required=True)
    parser.add_argument("--query-length", type=int, default=512)
    parser.add_argument("--candidate-length", type=int, default=192)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--label-field", default="gttype", help="Gold field for raw TypePro input")
    parser.add_argument("--preview-samples", type=int, default=2)
    parser.add_argument("--preview-max-chars", type=int, default=1600)
    parser.add_argument("--log-every", type=int, default=1000)
    return parser.parse_args()


def batched(records: Iterable[dict[str, Any]], batch_size: int) -> Iterator[list[dict[str, Any]]]:
    iterator = iter(records)
    while batch := list(islice(iterator, batch_size)):
        yield batch


def prepare_record(record: dict[str, Any], index: int, label_field: str) -> dict[str, Any]:
    # Final train/validation/test JSONL already contains formatted model inputs.
    if record.get("query") and isinstance(record.get("candidates"), list):
        candidates = [
            {"name": str(item.get("name") or ""), "text": str(item.get("text") or "")}
            for item in record["candidates"]
            if isinstance(item, dict) and item.get("name") and item.get("text")
        ]
        return {
            "id": record.get("id", index),
            "query": str(record["query"]),
            "candidates": candidates,
            "label": str(record.get("label") or "").strip(),
        }

    recommendations = normalize_recommendations(record)
    code_slice = get_slice(record)
    candidates = [
        {"name": item["name"], "text": format_candidate(item["name"], item["definition"])}
        for item in recommendations
    ]
    return {
        "id": record.get("id", index),
        "query": format_query(record, code_slice) if code_slice else "",
        "candidates": candidates,
        "label": str(record.get(label_field) or record.get("label") or "").strip(),
    }


@torch.inference_mode()
def rank_batch(
    model: CodeT5pBiEncoder,
    prepared: list[dict[str, Any]],
    device: torch.device,
    query_length: int,
    candidate_length: int,
    top_k: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any] | None] = [None] * len(prepared)
    valid_positions = [
        position for position, item in enumerate(prepared)
        if item["query"] and item["candidates"]
    ]
    valid_position_set = set(valid_positions)
    for position, item in enumerate(prepared):
        if position not in valid_position_set:
            results[position] = {
                "id": item["id"],
                "prediction": None,
                "ranking": [],
                "label": item["label"] or None,
                "error": "missing slice/query or recommendations/candidates",
            }
    if not valid_positions:
        return [item for item in results if item is not None]

    valid = [prepared[position] for position in valid_positions]
    query_tokens = model.tokenizer(
        [item["query"] for item in valid],
        padding=True,
        max_length=query_length,
        truncation=True,
        return_tensors="pt",
    ).to(device)
    flat_candidate_texts: list[str] = []
    offsets = [0]
    for item in valid:
        flat_candidate_texts.extend(candidate["text"] for candidate in item["candidates"])
        offsets.append(len(flat_candidate_texts))
    candidate_tokens = model.tokenizer(
        flat_candidate_texts,
        padding=True,
        max_length=candidate_length,
        truncation=True,
        return_tensors="pt",
    ).to(device)
    query_vectors = model.encode(query_tokens["input_ids"], query_tokens["attention_mask"])
    candidate_vectors = model.encode(candidate_tokens["input_ids"], candidate_tokens["attention_mask"])

    for valid_index, (position, item) in enumerate(zip(valid_positions, valid)):
        start, end = offsets[valid_index], offsets[valid_index + 1]
        scores = torch.matmul(candidate_vectors[start:end], query_vectors[valid_index]).float().cpu()
        full_order = scores.argsort(descending=True).tolist()
        ranking = [
            {"type": item["candidates"][candidate_index]["name"], "similarity": scores[candidate_index].item()}
            for candidate_index in full_order[:top_k]
        ]
        label_key = canonical_type_name(item["label"])
        gold_rank = next(
            (
                rank
                for rank, candidate_index in enumerate(full_order, start=1)
                if canonical_type_name(item["candidates"][candidate_index]["name"]) == label_key
            ),
            None,
        ) if label_key else None
        results[position] = {
            "id": item["id"],
            "prediction": ranking[0]["type"],
            "ranking": ranking,
            "label": item["label"] or None,
            "correct": gold_rank == 1 if label_key else None,
            "gold_rank": gold_rank,
        }
    return [item for item in results if item is not None]


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("batch-size must be positive")
    if args.top_k <= 0:
        raise ValueError("top-k must be positive")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = CodeT5pBiEncoder.load(args.checkpoint, device)
    model.eval()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")

    counts: dict[str, int | float] = {
        "input": 0,
        "written": 0,
        "errors": 0,
        "labeled": 0,
        "gold_in_candidates": 0,
        "top1_correct": 0,
        "reciprocal_rank_sum": 0.0,
    }
    previewed = 0
    indexed_records = (
        prepare_record(record, index, args.label_field)
        for index, record in enumerate(iter_records(args.input))
    )
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            for input_batch in batched(indexed_records, args.batch_size):
                counts["input"] += len(input_batch)
                results = rank_batch(
                    model, input_batch, device,
                    args.query_length, args.candidate_length, args.top_k,
                )
                for result in results:
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                    counts["written"] += 1
                    counts["errors"] += int("error" in result)
                    if result.get("label"):
                        counts["labeled"] += 1
                        if result.get("gold_rank") is not None:
                            counts["gold_in_candidates"] += 1
                            counts["reciprocal_rank_sum"] += 1.0 / result["gold_rank"]
                        counts["top1_correct"] += int(result.get("correct") is True)
                    if previewed < args.preview_samples:
                        previewed += 1
                        print(
                            f"\n[infer:sample] #{previewed}\n{json_preview(result, args.preview_max_chars)}",
                            flush=True,
                        )
                if args.log_every and counts["written"] % args.log_every < len(results):
                    print(f"[infer:progress] written={counts['written']:,}", flush=True)
        os.replace(temporary, output_path)
    finally:
        if temporary.exists():
            temporary.unlink()

    labeled = int(counts["labeled"])
    gold_in_candidates = int(counts["gold_in_candidates"])
    summary = {
        **{key: value for key, value in counts.items() if key != "reciprocal_rank_sum"},
        "candidate_recall": gold_in_candidates / labeled if labeled else None,
        "top1_accuracy": counts["top1_correct"] / labeled if labeled else None,
        "conditional_top1": counts["top1_correct"] / gold_in_candidates if gold_in_candidates else None,
        "mrr": counts["reciprocal_rank_sum"] / labeled if labeled else None,
        "output": str(output_path),
        "device": str(device),
    }
    input_path = Path(args.input)
    stats_path = input_path.parent / "preprocess_stats.json"
    split = input_path.stem if input_path.stem in {"train", "validation", "test"} else None
    if split and stats_path.exists():
        with stats_path.open(encoding="utf-8") as handle:
            preprocessing_stats = json.load(handle)
        eligible = int(preprocessing_stats.get(f"{split}_eligible_input", 0))
        source_gold_recommended = int(preprocessing_stats.get(f"{split}_gold_recommended", 0))
        summary["source_eligible_records"] = eligible
        summary["source_gold_recommended"] = source_gold_recommended
        summary["source_candidate_recall"] = source_gold_recommended / eligible if eligible else None
        summary["end_to_end_top1"] = counts["top1_correct"] / eligible if eligible else None
        summary["end_to_end_mrr_lower_bound"] = counts["reciprocal_rank_sum"] / eligible if eligible else None
    print(f"\n[infer:final-metrics]\n{json.dumps(summary, indent=2, ensure_ascii=False)}", flush=True)


if __name__ == "__main__":
    main()
