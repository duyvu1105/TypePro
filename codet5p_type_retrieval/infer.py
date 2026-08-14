from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from data_utils import format_candidate, format_query, get_slice, normalize_recommendations, read_records, write_jsonl
from model import CodeT5pBiEncoder


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rank TypePro recommendation types by CodeT5+ similarity")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--input", required=True, help="Raw TypePro JSON/JSONL; labels are not used")
    parser.add_argument("--output", required=True)
    parser.add_argument("--query-length", type=int, default=512)
    parser.add_argument("--candidate-length", type=int, default=192)
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


@torch.inference_mode()
def main() -> None:
    args = parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = CodeT5pBiEncoder.load(args.checkpoint, device)
    model.eval()
    output = []
    for index, record in enumerate(read_records(args.input)):
        recommendations = normalize_recommendations(record)
        code_slice = get_slice(record)
        if not code_slice or not recommendations:
            output.append({"id": record.get("id", index), "prediction": None, "ranking": [], "error": "missing slice or recommendations"})
            continue
        query_text = format_query(record, code_slice)
        candidate_texts = [format_candidate(item["name"], item["definition"]) for item in recommendations]
        query = model.tokenizer(query_text, max_length=args.query_length, truncation=True, return_tensors="pt").to(device)
        candidates = model.tokenizer(
            candidate_texts, padding=True, max_length=args.candidate_length,
            truncation=True, return_tensors="pt",
        ).to(device)
        query_vector = model.encode(query["input_ids"], query["attention_mask"])
        candidate_vectors = model.encode(candidates["input_ids"], candidates["attention_mask"])
        scores = torch.matmul(candidate_vectors, query_vector[0]).float().cpu()
        order = scores.argsort(descending=True).tolist()[: args.top_k]
        ranking = [{"type": recommendations[i]["name"], "similarity": scores[i].item()} for i in order]
        output.append({"id": record.get("id", index), "prediction": ranking[0]["type"], "ranking": ranking})
    write_jsonl(Path(args.output), output)
    print(json.dumps({"written": len(output), "output": args.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()
