"""Generate TypePro labels and report exact-match accuracy."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from generative_chat import chat_token_ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--model-name", default="Qwen/Qwen2.5-Coder-1.5B-Instruct")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--input-length", type=int, default=8192)
    parser.add_argument("--label-length", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=4)
    args = parser.parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(args.checkpoint)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    # Causal-LM generation from a padded batch must use the final non-pad token.
    tokenizer.padding_side = "left"
    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    base_model = AutoModelForCausalLM.from_pretrained(
        args.model_name,
        quantization_config=quantization_config,
        device_map={"": device},
        torch_dtype=torch.float16,
    )
    model = PeftModel.from_pretrained(base_model, args.checkpoint).to(device).eval()
    model.config.pad_token_id = tokenizer.pad_token_id
    with Path(args.input).open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    predictions = []
    correct = 0
    for start in range(0, len(rows), args.batch_size):
        batch = rows[start:start + args.batch_size]
        prompt_limit = max(1, args.input_length - args.label_length)
        prompt_ids = [
            chat_token_ids(tokenizer, row["input"])[:prompt_limit]
            for row in batch
        ]
        encoded = tokenizer.pad({"input_ids": prompt_ids}, padding=True, return_tensors="pt").to(device)
        with torch.inference_mode():
            generated = model.generate(
                **encoded, max_new_tokens=args.label_length,
                pad_token_id=tokenizer.pad_token_id,
            )
        prompt_length = encoded["input_ids"].shape[1]
        values = tokenizer.batch_decode(
            generated[:, prompt_length:], skip_special_tokens=True
        )
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
