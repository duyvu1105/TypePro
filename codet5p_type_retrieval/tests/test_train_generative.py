import sys
import ast
import math
from pathlib import Path
from types import SimpleNamespace

import pytest


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


@pytest.mark.parametrize("num_processes", [1, 2, 4])
@pytest.mark.parametrize("skip_update", [False, True])
def test_scheduler_advances_once_per_successful_update(num_processes, skip_update):
    """Exercise the actual scheduling statements without loading a Qwen model."""
    torch = pytest.importorskip("torch")
    source = ROOT / "codet5p_type_retrieval" / "train_generative.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    # Include any scheduler wrapping in the initialization, so reintroducing
    # AcceleratedScheduler's process multiplier fails the regression test.
    initialization = [
        node for node in main.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id in {
            "updates_per_epoch", "total_updates", "scheduler"
        } for target in node.targets)
    ]
    accumulation = next(
        node for node in ast.walk(main) if isinstance(node, ast.With)
        and "accelerator.accumulate" in ast.unparse(node.items[0].context_expr)
    )
    # Run the scheduler statement and its surrounding condition as written.
    stepping = [node for node in accumulation.body if "scheduler.step()" in ast.unparse(node)]
    assert stepping

    optimizer = torch.optim.SGD([torch.nn.Parameter(torch.zeros(1))], lr=2e-5)

    def linear_schedule(optimizer, warmup, total):
        return torch.optim.lr_scheduler.LambdaLR(
            optimizer,
            lambda step: step / warmup if step < warmup
            else max(0.0, (total - step) / (total - warmup)),
        )

    def prepare(scheduler):
        # Model the default AcceleratedScheduler multi-process adjustment.
        return SimpleNamespace(step=lambda: [scheduler.step() for _ in range(num_processes)])

    accelerator = SimpleNamespace(
        sync_gradients=False, optimizer_step_was_skipped=False, prepare=prepare,
    )
    scope = dict(
        math=math, args=SimpleNamespace(gradient_accumulation_steps=8, epochs=2),
        train_loader=range(2500), optimizer=optimizer, accelerator=accelerator,
        get_linear_schedule_with_warmup=linear_schedule,
    )
    exec(compile(ast.Module(body=initialization, type_ignores=[]), str(source), "exec"), scope)
    step_code = compile(ast.Module(body=stepping, type_ignores=[]), str(source), "exec")
    successful_updates = 0
    epoch_lrs = []
    for epoch in range(2):
        for batch in range(1, 2501):
            accelerator.sync_gradients = batch % 8 == 0 or batch == 2500
            accelerator.optimizer_step_was_skipped = skip_update and epoch == 0 and batch == 8
            if accelerator.sync_gradients and not accelerator.optimizer_step_was_skipped:
                optimizer.step()
                successful_updates += 1
            exec(step_code, scope)
        epoch_lrs.append(optimizer.param_groups[0]["lr"])
    assert scope["total_updates"] == 626
    assert scope["scheduler"].last_epoch == successful_updates == 626 - int(skip_update)
    assert 1e-5 < epoch_lrs[0] < 1.1e-5
    assert epoch_lrs[1] == pytest.approx(2e-5 / 595 if skip_update else 0.0)
