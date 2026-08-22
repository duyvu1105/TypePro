"""Qwen chat formatting shared by generative training and inference."""
from __future__ import annotations

from typing import Any

import torch


SYSTEM_PROMPT = "You are a helpful coding assistant."


def messages(instruction: str, response: str | None = None) -> list[dict[str, str]]:
    """Return the canonical conversation for one TypePro example."""
    result = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
    ]
    if response is not None:
        result.append({"role": "assistant", "content": response})
    return result


def chat_token_ids(tokenizer: Any, instruction: str, response: str | None = None) -> list[int]:
    """Apply the model-owned chat template without duplicating special tokens."""
    return tokenizer.apply_chat_template(
        messages(instruction, response),
        tokenize=True,
        add_generation_prompt=response is None,
    )


def left_pad_causal_batch(
    prompt_ids: list[list[int]],
    sequences: list[list[int]],
    pad_token_id: int,
) -> dict[str, torch.Tensor]:
    """Pad causal-LM examples on the left so the target stays in the suffix."""
    max_length = max(len(sequence) for sequence in sequences)
    input_ids = []
    attention_mask = []
    labels = []
    for prompt, sequence in zip(prompt_ids, sequences):
        padding = max_length - len(sequence)
        input_ids.append([pad_token_id] * padding + sequence)
        attention_mask.append([0] * padding + [1] * len(sequence))
        labels.append(
            [-100] * padding
            + [-100] * len(prompt)
            + sequence[len(prompt):]
        )
    return {
        "input_ids": torch.tensor(input_ids, dtype=torch.long),
        "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
        "labels": torch.tensor(labels, dtype=torch.long),
    }
