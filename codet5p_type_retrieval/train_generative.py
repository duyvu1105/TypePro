"""Fine-tune a causal code language model to generate the annotation label."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import torch
from accelerate import Accelerator
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from torch.utils.data import DataLoader, Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    get_linear_schedule_with_warmup,
)

from generative_chat import chat_token_ids, left_pad_causal_batch


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
    parser.add_argument("--input-length", type=int, default=8192)
    parser.add_argument("--label-length", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=16)
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
    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model_name,
        quantization_config=quantization_config,
        device_map={"": accelerator.local_process_index},
        torch_dtype=torch.float16,
    )
    model.config.pad_token_id = tokenizer.pad_token_id
    model = prepare_model_for_kbit_training(model)
    model = get_peft_model(model, LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    ))
    model.print_trainable_parameters()
    if args.gradient_checkpointing:
        model.gradient_checkpointing_enable()
        model.config.use_cache = False

    def collate(rows):
        prompt_limit = max(1, args.input_length - args.label_length)
        prompt_ids = []
        completion_ids = []
        for row in rows:
            full_prompt = chat_token_ids(tokenizer, row["input"])
            full_sequence = chat_token_ids(tokenizer, row["input"], row["label"])
            if full_sequence[:len(full_prompt)] != full_prompt:
                raise ValueError("Chat template did not preserve the prompt as a sequence prefix")
            prompt_ids.append(full_prompt[-prompt_limit:])
            completion_ids.append(full_sequence[len(full_prompt):len(full_prompt) + args.label_length])
        sequences = [prompt + completion for prompt, completion in zip(prompt_ids, completion_ids)]
        return left_pad_causal_batch(prompt_ids, sequences, tokenizer.pad_token_id)

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
                logits_to_keep = min(args.label_length + 1, batch["input_ids"].shape[1])
                model_batch = dict(batch)
                model_batch["labels"] = batch["labels"][:, -logits_to_keep:]
                loss = model(
                    **model_batch,
                    logits_to_keep=logits_to_keep,
                ).loss
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
                logits_to_keep = min(args.label_length + 1, batch["input_ids"].shape[1])
                model_batch = dict(batch)
                model_batch["labels"] = batch["labels"][:, -logits_to_keep:]
                loss = model(
                    **model_batch,
                    logits_to_keep=logits_to_keep,
                ).loss
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
