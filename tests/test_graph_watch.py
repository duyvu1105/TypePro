from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kaggle_notebooks'))
import graph_watch


def job(status='COMPLETE'):
    return dict(kernel='owner/shard', dataset='owner/graph', status='submitted',
                remote_status=status, cli_output='Kernel version 8 successfully pushed.', dataset_baseline=3)


@pytest.mark.parametrize('status', ['RUNNING', 'QUEUED', 'ERROR'])
def test_watcher_never_merges_incomplete_or_failed_shards(status, monkeypatch, tmp_path):
    monkeypatch.setattr(graph_watch, 'run_push', lambda *a: pytest.fail('unexpected merge submission'))
    state = dict(jobs=[job(status)])
    if status == 'ERROR':
        with pytest.raises(RuntimeError, match='Graph shard failed'):
            graph_watch.merge_tick(None, None, tmp_path, state, lambda: None, tmp_path, None)
    else:
        assert not graph_watch.merge_tick(None, None, tmp_path, state, lambda: None, tmp_path, None)


def test_watcher_requires_new_dataset_version_and_exact_kernel_version(monkeypatch, tmp_path):
    state = dict(jobs=[job()])
    api = SimpleNamespace(kernels_status=lambda ref: SimpleNamespace(status='COMPLETE'))
    monkeypatch.setattr(graph_watch, 'kernel_version', lambda *args: 8)
    monkeypatch.setattr(graph_watch, 'exact_dataset', lambda *args: SimpleNamespace(current_version_number=3))
    monkeypatch.setattr(graph_watch, 'run_push', lambda *args: pytest.fail('stale shard Dataset'))
    assert not graph_watch.merge_tick(api, None, tmp_path, state, lambda: None, tmp_path, None)
    assert state['merge']['waiting_for_dataset'] == 'owner/graph'
    monkeypatch.setattr(graph_watch, 'kernel_version', lambda *args: 9)
    with pytest.raises(RuntimeError, match='version/status changed'):
        graph_watch.merge_tick(api, None, tmp_path, state, lambda: None, tmp_path, None)
