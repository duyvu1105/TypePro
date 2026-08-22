"""Fine-tune a causal code language model to generate the annotation label."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import torch
from accelerate import Accelerator
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, get_linear_schedule_with_warmup


class JsonlDataset(Dataset):
    def __init__(self, path: Path):
        with path.open(encoding="utf-8") as handle:
            self.rows = [json.loads(line) for line in handle if line.strip()]

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        return self.rows[index]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--model-name", default="Qwen/Qwen2.5-Coder-1.5B-Instruct")
    parser.add_argument("--input-length", type=int, default=32768)
    parser.add_argument("--label-length", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--mixed-precision", default="fp16")
    parser.add_argument("--gradient-checkpointing", action="store_true")
    parser.add_argument("--seed", type=int, default=13)
    args = parser.parse_args()
    random.seed(args.seed)
    torch.manual_seed(args.seed)

    accelerator = Accelerator(
        mixed_precision=args.mixed_precision,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
    )
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(args.model_name)
    model.config.pad_token_id = tokenizer.pad_token_id
    if args.gradient_checkpointing:
        model.gradient_checkpointing_enable()
        model.config.use_cache = False

    def collate(rows):
        prompt_limit = max(1, args.input_length - args.label_length)
        prompt_ids = tokenizer(
            [row["input"] for row in rows], padding=False, truncation=True,
            max_length=prompt_limit, add_special_tokens=True,
        )["input_ids"]
        label_ids = tokenizer(
            [row["label"] for row in rows], padding=False, truncation=True,
            max_length=args.label_length, add_special_tokens=True,
        )["input_ids"]
        sequences = [prompt + label for prompt, label in zip(prompt_ids, label_ids)]
        max_length = max(len(sequence) for sequence in sequences)
        input_ids = []
        attention_mask = []
        labels = []
        for prompt, sequence in zip(prompt_ids, sequences):
            padding = max_length - len(sequence)
            input_ids.append(sequence + [tokenizer.pad_token_id] * padding)
            attention_mask.append([1] * len(sequence) + [0] * padding)
            labels.append([-100] * len(prompt) + sequence[len(prompt):] + [-100] * padding)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
        }

    data_dir = Path(args.data_dir)
    train_loader = DataLoader(
        JsonlDataset(data_dir / "train.jsonl"), batch_size=args.batch_size,
        shuffle=True, collate_fn=collate,
    )
    valid_loader = DataLoader(
        JsonlDataset(data_dir / "validation.jsonl"), batch_size=args.batch_size,
        collate_fn=collate,
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    steps = max(1, len(train_loader) * args.epochs // args.gradient_accumulation_steps)
    scheduler = get_linear_schedule_with_warmup(optimizer, max(1, steps // 20), steps)
    model, optimizer, train_loader, valid_loader, scheduler = accelerator.prepare(
        model, optimizer, train_loader, valid_loader, scheduler
    )
    accelerator.print(json.dumps({
        "status": "training_started",
        "train_samples": len(train_loader.dataset),
        "validation_samples": len(valid_loader.dataset),
        "train_batches_per_epoch": len(train_loader),
        "epochs": args.epochs,
    }))
    output = Path(args.output_dir)
    best_loss = float("inf")
    for epoch in range(args.epochs):
        model.train()
        accelerator.print(f"epoch {epoch + 1}/{args.epochs} started", flush=True)
        for batch_index, batch in enumerate(train_loader, start=1):
            with accelerator.accumulate(model):
                loss = model(**batch).loss
                accelerator.backward(loss)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()
            if batch_index == 1 or batch_index % 10 == 0:
                accelerator.print(
                    f"epoch {epoch + 1}/{args.epochs} batch "
                    f"{batch_index}/{len(train_loader)} loss={loss.item():.4f}",
                    flush=True,
                )
        model.eval()
        losses = []
        with torch.no_grad():
            for batch in valid_loader:
                loss = model(**batch).loss
                losses.append(accelerator.gather(loss.detach().repeat(batch["labels"].shape[0])))
        validation_loss = torch.cat(losses).mean().item() if losses else 0.0
        accelerator.print(json.dumps({"epoch": epoch + 1, "validation_loss": validation_loss}))
        if validation_loss < best_loss:
            best_loss = validation_loss
            accelerator.wait_for_everyone()
            unwrapped = accelerator.unwrap_model(model)
            unwrapped.save_pretrained(
                output / "best", is_main_process=accelerator.is_main_process,
                save_function=accelerator.save,
            )
            if accelerator.is_main_process:
                tokenizer.save_pretrained(output / "best")


if __name__ == "__main__":
    main()
