import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "codet5p_type_retrieval"))

from length_grouping import LengthGroupedSampler


def test_length_grouped_sampler_keeps_similar_lengths_in_each_batch():
    lengths = [1, 100, 2, 99, 3, 98, 4, 97]
    sampler = LengthGroupedSampler(
        lengths, batch_size=2, seed=13, window_batches=4
    )

    ordered = list(sampler)
    batches = [ordered[index:index + 2] for index in range(0, len(ordered), 2)]

    assert sorted(ordered) == list(range(len(lengths)))
    assert all(
        abs(lengths[first] - lengths[second]) <= 1
        for first, second in batches
    )


def test_length_grouped_sampler_reshuffles_between_epochs():
    sampler = LengthGroupedSampler(
        list(range(40)), batch_size=2, seed=13, window_batches=5
    )

    assert list(sampler) != list(sampler)
