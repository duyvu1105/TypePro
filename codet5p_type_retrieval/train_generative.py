"""Fine-tune a causal code language model to generate the annotation label."""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

import torch
from accelerate import Accelerator
from accelerate.utils import set_seed
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from torch.utils.data import DataLoader, Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    get_linear_schedule_with_warmup,
)
from tqdm.auto import tqdm

from data_utils import select_training_samples
from generative_chat import chat_token_ids, left_pad_causal_batch
from length_grouping import LengthGroupedSampler


class JsonlDataset(Dataset):
    def __init__(self, path: Path):
        with path.open(encoding="utf-8") as handle:
            self.rows = [json.loads(line) for line in handle if line.strip()]

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        return self.rows[index]


def training_sequence_length(row, tokenizer, input_length: int, label_length: int) -> int:
    """Return the post-truncation sequence length used by ``collate``."""
    prompt_ids = chat_token_ids(tokenizer, row["input"])
    full_ids = chat_token_ids(tokenizer, row["input"], row["label"])
    if full_ids[:len(prompt_ids)] != prompt_ids:
        raise ValueError("Chat template did not preserve the prompt as a sequence prefix")
    prompt_limit = max(1, input_length - label_length)
    completion_length = min(max(0, len(full_ids) - len(prompt_ids)), label_length)
    return min(len(prompt_ids), prompt_limit) + completion_length


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
    parser.add_argument(
        "--attn-implementation",
        choices=("sdpa", "flash_attention_2", "eager"),
        default="sdpa",
        help="Attention backend; SDPA is memory-efficient and needs no extra package",
    )
    parser.add_argument(
        "--gradient-checkpointing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Trade additional compute for lower activation memory (enabled by default)",
    )
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument(
        "--train-samples",
        type=int,
        default=None,
        help="Number of deterministic random training samples; omitted uses the full train split",
    )
    parser.add_argument("--preview-samples", type=int, default=2)
    parser.add_argument("--preview-max-chars", type=int, default=1200)
    parser.add_argument("--log-every", type=int, default=10)
    parser.add_argument(
        "--group-by-length",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Group similarly sized samples within shuffled windows to reduce padding",
    )
    parser.add_argument("--length-grouping-window", type=int, default=50)
    args = parser.parse_args()
    accelerator = Accelerator(
        mixed_precision=args.mixed_precision,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
    )
    # Accelerator must be initialized before device-specific seeding because
    # set_seed reads the distributed process index from AcceleratorState.
    set_seed(args.seed, device_specific=True)
    random.seed(args.seed)
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
        attn_implementation=args.attn_implementation,
    )
    model.config.pad_token_id = tokenizer.pad_token_id
    model = prepare_model_for_kbit_training(
        model,
        use_gradient_checkpointing=args.gradient_checkpointing,
        gradient_checkpointing_kwargs={"use_reentrant": False},
    )
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
            # Preserve the structured header at the beginning of the prompt.
            # Inference uses the same policy so train/eval see identical inputs.
            prompt_ids.append(full_prompt[:prompt_limit])
            completion_ids.append(full_sequence[len(full_prompt):len(full_prompt) + args.label_length])
        sequences = [prompt + completion for prompt, completion in zip(prompt_ids, completion_ids)]
        return left_pad_causal_batch(prompt_ids, sequences, tokenizer.pad_token_id)

    data_dir = Path(args.data_dir)
    full_train_dataset = JsonlDataset(data_dir / "train.jsonl")
    train_dataset = select_training_samples(
        full_train_dataset, args.train_samples, args.seed
    )
    train_sampler = None
    if args.group_by_length:
        accelerator.print("Measuring train sequence lengths for bucketing...", flush=True)
        train_lengths = [
            training_sequence_length(
                row, tokenizer, args.input_length, args.label_length
            )
            for row in train_dataset
        ]
        train_sampler = LengthGroupedSampler(
            train_lengths,
            batch_size=args.batch_size,
            seed=args.seed,
            window_batches=args.length_grouping_window,
        )
    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        sampler=train_sampler,
        shuffle=train_sampler is None,
        collate_fn=collate,
    )
    valid_loader = DataLoader(
        JsonlDataset(data_dir / "validation.jsonl"), batch_size=args.batch_size,
        collate_fn=collate,
    )
    trainable_parameters = [
        parameter for parameter in model.parameters() if parameter.requires_grad
    ]
    optimizer = torch.optim.AdamW(trainable_parameters, lr=args.learning_rate)
    # Prepare the dataloader first: in multi-GPU mode Accelerate shards it,
    # so len(train_loader) now reflects the number of local micro-batches.
    model, optimizer, train_loader, valid_loader = accelerator.prepare(
        model, optimizer, train_loader, valid_loader
    )
    updates_per_epoch = max(
        1, math.ceil(len(train_loader) / args.gradient_accumulation_steps)
    )
    total_updates = updates_per_epoch * args.epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer, max(1, total_updates // 20), total_updates
    )
    # total_updates already uses the sharded loader's optimizer-update count.
    # Keep this scheduler unwrapped: AcceleratedScheduler can step once per
    # process, which would exhaust this schedule early on multiple GPUs.
    accelerator.print(json.dumps({
        "status": "training_started",
        "train_samples": len(train_loader.dataset),
        "full_train_samples": len(full_train_dataset),
        "validation_samples": len(valid_loader.dataset),
        "train_batches_per_epoch": len(train_loader),
        "updates_per_epoch": updates_per_epoch,
        "total_updates": total_updates,
        "epochs": args.epochs,
        "group_by_length": args.group_by_length,
        "length_grouping_window_batches": (
            args.length_grouping_window if args.group_by_length else None
        ),
    }))

    if args.preview_samples > 0:
        preview_batch = next(iter(train_loader))
        accelerator.print("===== TRAINING INPUT PREVIEW =====", flush=True)
        preview_count = min(args.preview_samples, preview_batch["input_ids"].shape[0])
        for sample_index in range(preview_count):
            input_ids = preview_batch["input_ids"][sample_index]
            attention_mask = preview_batch["attention_mask"][sample_index].bool()
            labels = preview_batch["labels"][sample_index]
            active_input_ids = input_ids[attention_mask].detach().cpu()
            active_labels = labels[labels != -100].detach().cpu()
            prompt_token_count = active_input_ids.numel() - active_labels.numel()
            prompt_ids = active_input_ids[:prompt_token_count]
            preview = {
                "sample": sample_index,
                "prompt_tokens": int(prompt_ids.numel()),
                "label_tokens": int(active_labels.numel()),
                "prompt": tokenizer.decode(
                    prompt_ids.tolist(), skip_special_tokens=False
                )[:args.preview_max_chars],
                "target": tokenizer.decode(
                    active_labels.tolist(), skip_special_tokens=False
                )[:args.preview_max_chars],
                "teacher_forcing_input": tokenizer.decode(
                    active_input_ids.tolist(), skip_special_tokens=False
                )[:args.preview_max_chars],
            }
            accelerator.print(json.dumps(preview, ensure_ascii=False), flush=True)
        accelerator.print("===== END TRAINING INPUT PREVIEW =====", flush=True)

    output = Path(args.output_dir)
    best_loss = float("inf")
    progress = tqdm(
        total=total_updates,
        desc="training",
        unit="update",
        disable=not accelerator.is_local_main_process,
    )
    for epoch in range(args.epochs):
        model.train()
        accelerator.print(f"epoch {epoch + 1}/{args.epochs} started", flush=True)
        progress.set_description(f"epoch {epoch + 1}/{args.epochs}")
        loss_window = []
        # [summed token loss, supervised token count] across all training batches.
        epoch_loss_totals = torch.zeros(2, dtype=torch.float64, device=accelerator.device)
        last_grad_norm = None
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
                if accelerator.sync_gradients:
                    grad_norm = accelerator.clip_grad_norm_(model.parameters(), 1.0)
                    last_grad_norm = float(grad_norm.detach().float().item())
                optimizer.step()
                if accelerator.sync_gradients and not accelerator.optimizer_step_was_skipped:
                    scheduler.step()
                optimizer.zero_grad()
                if accelerator.sync_gradients:
                    progress.update(1)
                    progress.set_postfix(
                        loss=f"{loss.detach().float().item():.4f}",
                        lr=f"{optimizer.param_groups[0]['lr']:.2e}",
                    )
            loss_window.append(float(loss.detach().float().item()))
            # Causal-LM loss shifts labels by one; the first label in the
            # retained suffix has no corresponding prediction in that suffix.
            label_tokens = (model_batch["labels"][:, 1:] != -100).sum()
            epoch_loss_totals[0] += loss.detach().double() * label_tokens
            epoch_loss_totals[1] += label_tokens
            if (
                batch_index == 1
                or (args.log_every > 0 and batch_index % args.log_every == 0)
            ):
                average_loss = sum(loss_window) / len(loss_window)
                grad_norm_text = (
                    f"{last_grad_norm:.4f}" if last_grad_norm is not None else "n/a"
                )
                accelerator.print(
                    f"epoch {epoch + 1}/{args.epochs} batch "
                    f"{batch_index}/{len(train_loader)} "
                    f"loss_avg={average_loss:.4f} "
                    f"lr={optimizer.param_groups[0]['lr']:.3e} "
                    f"grad_norm={grad_norm_text}",
                    flush=True,
                )
                loss_window.clear()
        epoch_loss_totals = accelerator.reduce(epoch_loss_totals, reduction="sum")
        train_loss_epoch = (
            epoch_loss_totals[0] / epoch_loss_totals[1].clamp_min(1)
        ).item()
        accelerator.print(json.dumps({
            "epoch": epoch + 1,
            "train_loss_epoch": train_loss_epoch,
            "train_label_tokens": int(epoch_loss_totals[1].item()),
        }), flush=True)
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
        accelerator.print(json.dumps({
            "epoch": epoch + 1,
            "train_loss_epoch": train_loss_epoch,
            "validation_loss": validation_loss,
        }))
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
    progress.close()


if __name__ == "__main__":
    main()
