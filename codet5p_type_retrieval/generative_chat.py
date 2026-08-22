"""Qwen chat formatting shared by generative training and inference."""
from __future__ import annotations

from typing import Any


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
