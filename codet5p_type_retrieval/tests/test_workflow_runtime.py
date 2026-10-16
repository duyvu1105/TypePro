"""Workflow audits and compatibility survive failed and resumed commands."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from typepro.runtime import run_main


@pytest.mark.parametrize('failure,status', [(None, 'complete'), (RuntimeError, 'failed'), (KeyboardInterrupt, 'interrupted')])
def test_runtime_records_lifecycle_and_redacts_secrets(tmp_path, monkeypatch, failure, status):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'sensitive-test-token')

    def command():
        print('credential sensitive-test-token')
        if failure:
            raise failure('sensitive-test-token')

    if failure:
        with pytest.raises(failure):
            run_main(command, 'test', audit_root=tmp_path)
    else:
        run_main(command, 'test', audit_root=tmp_path)
    folder, = tmp_path.iterdir()
    state = json.loads((folder / 'run.json').read_text())
    assert state['status'] == status
    assert state['elapsed_seconds'] >= 0
    assert 'sensitive-test-token' not in (folder / 'console.log').read_text()
    assert 'sensitive-test-token' not in (folder / 'run.json').read_text()
    assert '[REDACTED]' in (folder / 'console.log').read_text()


def test_legacy_import_is_the_same_module():
    import prepare_dataset
    from typepro.data import prepare
    assert prepare_dataset is prepare


def test_deepseek_lock_prevents_concurrent_writer(tmp_path):
    from typepro.inference.deepseek import exclusive_run_lock
    lock = tmp_path / 'inference.lock'
    with exclusive_run_lock(lock):
        with pytest.raises(RuntimeError, match='Another DeepSeek'):
            with exclusive_run_lock(lock):
                pytest.fail('Acquired a lock already held by another writer')
    with exclusive_run_lock(lock):
        pass
