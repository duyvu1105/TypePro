"""Length-aware sampling utilities for the generative training pipeline."""
from __future__ import annotations

import torch
from torch.utils.data import Sampler


class LengthGroupedSampler(Sampler[int]):
    """Shuffle examples, then sort small windows by their padded length."""

    def __init__(
        self,
        lengths: list[int],
        batch_size: int,
        seed: int,
        window_batches: int = 50,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if window_batches < 1:
            raise ValueError("window_batches must be positive")
        self.lengths = lengths
        self.window_size = batch_size * window_batches
        self.generator = torch.Generator().manual_seed(seed)

    def __len__(self) -> int:
        return len(self.lengths)

    def __iter__(self):
        indices = torch.randperm(
            len(self.lengths), generator=self.generator
        ).tolist()
        grouped = []
        for start in range(0, len(indices), self.window_size):
            window = indices[start:start + self.window_size]
            window.sort(key=self.lengths.__getitem__, reverse=True)
            grouped.extend(window)
        return iter(grouped)
