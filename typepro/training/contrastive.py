from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import torch
from accelerate import Accelerator
from torch.optim import AdamW
from torch.utils.data import DataLoader
from tqdm.auto import tqdm
from transformers import get_cosine_schedule_with_warmup, set_seed

from data_utils import (
    ContrastiveCollator,
    JsonlDataset,
    canonical_type_name,
    print_jsonl_samples,
    select_training_samples,
)
from model import CodeT5pBiEncoder


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Contrastive fine-tuning for TypePro type retrieval")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--model-name", default="Salesforce/codet5p-220m")
    parser.add_argument("--projection-dim", type=int, default=256)
    parser.add_argument("--query-length", type=int, default=512)
    parser.add_argument("--candidate-length", type=int, default=192)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=4)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--warmup-ratio", type=float, default=0.06)
    parser.add_argument("--temperature", type=float, default=0.07)
    parser.add_argument("--mixed-precision", choices=("no", "fp16", "bf16"), default="fp16")
    parser.add_argument("--gradient-checkpointing", action="store_true")
    parser.add_argument("--num-workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument(
        "--train-samples",
        type=int,
        default=None,
        help="Number of deterministic random training samples; omitted uses the full train split",
    )
    parser.add_argument("--preview-samples", type=int, default=2, help="Samples printed per split before training; 0 disables")
    parser.add_argument("--preview-max-chars", type=int, default=1600, help="Maximum characters per sample; 0 prints all")
    return parser.parse_args()


@torch.no_grad()
def evaluate(model, loader, accelerator: Accelerator, temperature: float) -> dict[str, float]:
    model.eval()
    total_loss = total = correct = 0.0
    reciprocal_rank = 0.0
    for batch in loader:
        candidate_names = batch.pop("candidate_names")
        gold = batch.pop("gold")
        loss, scores = model(batch, temperature)
        predictions = scores.argmax(dim=1)
        ranks = scores.argsort(dim=1, descending=True)
        for row_index, prediction in enumerate(predictions.tolist()):
            total += 1
            correct += canonical_type_name(candidate_names[row_index][prediction]) == canonical_type_name(gold[row_index])
            positive_index = int(batch["labels"][row_index])
            rank = (ranks[row_index] == positive_index).nonzero(as_tuple=False)[0, 0].item() + 1
            reciprocal_rank += 1.0 / rank
        total_loss += loss.item() * len(gold)
    values = torch.tensor([total_loss, total, correct, reciprocal_rank], device=accelerator.device)
    values = accelerator.reduce(values, reduction="sum").tolist()
    model.train()
    return {"loss": values[0] / max(values[1], 1), "top1": values[2] / max(values[1], 1), "mrr": values[3] / max(values[1], 1)}


def main() -> None:
    args = parse_args()
    set_seed(args.seed)
    accelerator = Accelerator(
        mixed_precision=args.mixed_precision,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
    )
    data_dir = Path(args.data_dir)
    split_paths = {split: data_dir / f"{split}.jsonl" for split in ("train", "validation", "test")}
    missing_files = [str(path) for path in split_paths.values() if not path.exists()]
    if missing_files:
        raise FileNotFoundError(f"Missing dataset split files: {missing_files}")
    datasets = {split: JsonlDataset(path) for split, path in split_paths.items()}
    train_data = select_training_samples(
        datasets["train"], args.train_samples, args.seed
    )
    validation_data = datasets["validation"]
    if not train_data or not validation_data:
        raise ValueError("train.jsonl and validation.jsonl must both contain examples")
    dataset_summary = {
        "data_dir": str(data_dir.resolve()),
        "records": {split: len(dataset) for split, dataset in datasets.items()},
        "total_records": sum(len(dataset) for dataset in datasets.values()),
        "file_bytes": {split: split_paths[split].stat().st_size for split in split_paths},
    }
    accelerator.print(f"\n[train:dataset-full-counts]\n{json.dumps(dataset_summary, indent=2, ensure_ascii=False)}")
    if accelerator.is_main_process:
        for split, path in split_paths.items():
            print_jsonl_samples(
                path,
                args.preview_samples,
                args.preview_max_chars,
                title=f"training input {split}",
            )

    model = CodeT5pBiEncoder(args.model_name, args.projection_dim, args.gradient_checkpointing)
    parameter_summary = {
        "checkpoint": args.model_name,
        "total_parameters_used": sum(parameter.numel() for parameter in model.parameters()),
        "trainable_parameters": sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad),
        "projection_dim": args.projection_dim,
    }
    accelerator.print(f"\n[train:model]\n{json.dumps(parameter_summary, indent=2, ensure_ascii=False)}")
    train_loader = DataLoader(
        train_data, batch_size=args.batch_size, shuffle=True,
        num_workers=args.num_workers, collate_fn=ContrastiveCollator(model.tokenizer, args.query_length, args.candidate_length, True),
    )
    validation_loader = DataLoader(
        validation_data, batch_size=args.batch_size, shuffle=False,
        num_workers=args.num_workers, collate_fn=ContrastiveCollator(model.tokenizer, args.query_length, args.candidate_length, False),
    )
    optimizer = AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    updates_per_epoch = math.ceil(len(train_loader) / args.gradient_accumulation_steps)
    total_updates = updates_per_epoch * args.epochs
    accelerator.print(json.dumps({
        "training_examples": len(train_data),
        "validation_examples": len(validation_data),
        "micro_batch_size": args.batch_size,
        "gradient_accumulation_steps": args.gradient_accumulation_steps,
        "effective_batch_size_per_process": args.batch_size * args.gradient_accumulation_steps,
        "epochs": args.epochs,
        "optimizer_updates_per_epoch": updates_per_epoch,
        "total_optimizer_updates": total_updates,
    }, indent=2, ensure_ascii=False))
    scheduler = get_cosine_schedule_with_warmup(
        optimizer, int(total_updates * args.warmup_ratio), total_updates,
    )
    model, optimizer, train_loader, validation_loader, scheduler = accelerator.prepare(
        model, optimizer, train_loader, validation_loader, scheduler,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    history, best_top1 = [], -1.0
    progress = tqdm(range(total_updates), disable=not accelerator.is_local_main_process)
    for epoch in range(args.epochs):
        model.train()
        for batch in train_loader:
            batch.pop("candidate_names")
            batch.pop("gold")
            with accelerator.accumulate(model):
                loss, _ = model(batch, args.temperature)
                accelerator.backward(loss)
                if accelerator.sync_gradients:
                    accelerator.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()
            if accelerator.sync_gradients:
                progress.update(1)
                progress.set_postfix(loss=f"{loss.item():.4f}")

        metrics = evaluate(model, validation_loader, accelerator, args.temperature)
        metrics["epoch"] = epoch + 1
        history.append(metrics)
        accelerator.print(json.dumps(metrics, ensure_ascii=False))
        if metrics["top1"] > best_top1:
            best_top1 = metrics["top1"]
            accelerator.wait_for_everyone()
            if accelerator.is_main_process:
                unwrapped = accelerator.unwrap_model(model)
                state = accelerator.get_state_dict(model)
                unwrapped.save(output_dir / "best", state)

    if accelerator.is_main_process:
        with (output_dir / "history.json").open("w", encoding="utf-8") as handle:
            json.dump(history, handle, indent=2)


if __name__ == "__main__":
    main()
