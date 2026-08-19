"""Generate TypePro labels and report exact-match accuracy."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--input-length", type=int, default=768)
    parser.add_argument("--label-length", type=int, default=64)
    parser.add_argument("--batch-size", type=int, default=4)
    args = parser.parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(args.checkpoint)
    model = AutoModelForSeq2SeqLM.from_pretrained(args.checkpoint).to(device).eval()
    with Path(args.input).open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    predictions = []
    correct = 0
    for start in range(0, len(rows), args.batch_size):
        batch = rows[start:start + args.batch_size]
        encoded = tokenizer(
            [row["input"] for row in batch], padding=True, truncation=True,
            max_length=args.input_length, return_tensors="pt",
        ).to(device)
        with torch.inference_mode():
            generated = model.generate(**encoded, max_new_tokens=args.label_length)
        values = tokenizer.batch_decode(generated, skip_special_tokens=True)
        for row, prediction in zip(batch, values):
            prediction = prediction.strip()
            correct += prediction == row["label"]
            predictions.append({
                "id": row["id"], "prediction": prediction,
                "label": row["label"], "exact_match": prediction == row["label"],
            })
    output = Path(args.output)
    with output.open("w", encoding="utf-8") as handle:
        for item in predictions:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(json.dumps({
        "rows": len(rows), "exact_matches": correct,
        "exact_match_accuracy": correct / len(rows) if rows else 0.0,
        "output": str(output),
    }, indent=2))


if __name__ == "__main__":
    main()
