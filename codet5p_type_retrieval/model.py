from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
from torch import nn
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from data_utils import SPECIAL_TOKENS


class CodeT5pBiEncoder(nn.Module):
    def __init__(self, model_name: str, projection_dim: int = 256, gradient_checkpointing: bool = False):
        super().__init__()
        full_model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        added = self.tokenizer.add_special_tokens({"additional_special_tokens": SPECIAL_TOKENS})
        if added:
            full_model.resize_token_embeddings(len(self.tokenizer))
        if gradient_checkpointing:
            full_model.gradient_checkpointing_enable()
            full_model.config.use_cache = False
        self.encoder = full_model.get_encoder()
        hidden_size = int(full_model.config.d_model)
        self.projection = nn.Sequential(
            nn.Linear(hidden_size, hidden_size),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_size, projection_dim),
        )
        self.model_name = model_name
        self.projection_dim = projection_dim

    def encode(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        hidden = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        mask = attention_mask.unsqueeze(-1).to(hidden.dtype)
        pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp_min(1.0)
        return F.normalize(self.projection(pooled), p=2, dim=-1)

    def forward(self, batch: dict[str, Any], temperature: float = 0.07) -> tuple[torch.Tensor, torch.Tensor]:
        query = self.encode(batch["query_input_ids"], batch["query_attention_mask"])
        candidate = self.encode(batch["candidate_input_ids"], batch["candidate_attention_mask"])
        batch_size, max_candidates = batch["candidate_mask"].shape
        candidate = candidate.reshape(batch_size, max_candidates, -1)
        scores = torch.einsum("bd,bmd->bm", query, candidate) / temperature
        scores = scores.masked_fill(~batch["candidate_mask"], torch.finfo(scores.dtype).min)
        return F.cross_entropy(scores, batch["labels"]), scores

    def save(self, output_dir: str | Path, state_dict: dict[str, torch.Tensor] | None = None) -> None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        torch.save(state_dict or self.state_dict(), output_dir / "model.pt")
        self.tokenizer.save_pretrained(output_dir / "tokenizer")
        with (output_dir / "retriever_config.json").open("w", encoding="utf-8") as handle:
            json.dump({"model_name": self.model_name, "projection_dim": self.projection_dim}, handle, indent=2)

    @classmethod
    def load(cls, checkpoint_dir: str | Path, device: str | torch.device = "cpu") -> "CodeT5pBiEncoder":
        checkpoint_dir = Path(checkpoint_dir)
        with (checkpoint_dir / "retriever_config.json").open(encoding="utf-8") as handle:
            config = json.load(handle)
        model = cls(config["model_name"], config["projection_dim"])
        # The saved tokenizer includes the special-token mapping used during training.
        model.tokenizer = AutoTokenizer.from_pretrained(checkpoint_dir / "tokenizer")
        state = torch.load(checkpoint_dir / "model.pt", map_location="cpu", weights_only=True)
        model.load_state_dict(state)
        return model.to(device)
