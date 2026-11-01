import json
from pathlib import Path

import pytest

from ssh_notebooks.run_type_changing import command_for, process_identity, validate_data, require_training_ready
from typepro.training.type_changing import build
from test_type_changing import row


def test_command_matches_baseline_recipe_and_runs_automatic_inference():
    baseline = dict(model='base', mixed_precision='fp16', input_length=6144, label_length=64,
                    epochs=2, batch_size=1, gradient_accumulation_steps=16,
                    learning_rate=1e-4, seed=13)
    cmd = command_for(baseline, Path('/data'), Path('/output'))
    for flag, value in [('input-length', '6144'), ('epochs', '2'), ('model-name', 'base'),
                        ('gradient-accumulation-steps', '16'), ('learning-rate', '0.0001')]:
        assert cmd[cmd.index('--' + flag) + 1] == value
    assert '--group-by-length' in cmd and '--infer-after-training' in cmd


def test_validator_detects_tampered_eval_and_code(tmp_path):
    import hashlib
    source = tmp_path / 'source'
    source.mkdir()
    splits = {}
    for s in ('train', 'validation', 'test'):
        p = source / f'{s}.jsonl'
        p.write_text(json.dumps(row()) + '\n')
        splits[s] = dict(rows=1, file=p.name, sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    (source / 'manifest.json').write_text(json.dumps(dict(output=splits)))
    data = tmp_path / 'derived'
    build(source, data)
    baseline = dict(seed=13, dataset_splits=splits, data_dir=str(source))
    validate_data(data, baseline)
    wrong_code = tmp_path / 'wrong.py'
    wrong_code.write_text('# changed')
    with pytest.raises(ValueError, match='augmentation code'):
        validate_data(data, baseline, wrong_code)
    (data / 'test.jsonl').write_text('tampered')
    with pytest.raises(ValueError, match='test hash'):
        validate_data(data, baseline)


def test_wait_uses_process_birth_identity():
    import os
    assert process_identity(os.getpid()) is not None
    assert process_identity(999999999) is None


def test_training_coverage_gate_rejects_old_small_pilot_and_wrong_budget():
    from typepro.training.contract_changing import POLICY
    baseline=dict(model='Qwen/base',input_length=6144,label_length=64)
    with pytest.raises(ValueError,match='coverage gate'):
        require_training_ready(dict(policy='type-changing-v1',counts=dict(synthetic_rows=133)),baseline)
    audit=dict(policy=POLICY,readiness=dict(passed=True),tokenizer='Qwen/base',limits=dict(prompt_limit=6080),
               independent_verification=dict(passed=True,label_length=64))
    require_training_ready(audit,baseline)
    audit['limits']['prompt_limit']=8192
    with pytest.raises(ValueError,match='budget'):
        require_training_ready(audit,baseline)
