from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kaggle_notebooks'))
import graph_profile


def storage_function():
    namespace = {'Path': Path}
    exec(graph_profile.graph_merge_storage_source(), namespace)
    return namespace['graph_merge_workspace']


def test_merge_selects_volume_with_room_for_raw_and_archive(tmp_path, monkeypatch):
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    (inputs / 'outcomes.jsonl').write_bytes(b'evidence' * 100)
    small, large = tmp_path / 'working', tmp_path / 'scratch'
    small.mkdir()
    large.mkdir()
    monkeypatch.setattr(shutil, 'disk_usage', lambda path: SimpleNamespace(
        free=100 if Path(path) == small else 100 * 1024**3))
    workspace, report = storage_function()([inputs], [small, large])
    assert workspace.parent == large
    assert report['input_bytes'] == 800
    assert report['required_bytes'] == 1600 + 2 * 1024**3
    assert list(workspace.iterdir()) == []
    assert (inputs / 'outcomes.jsonl').read_bytes() == b'evidence' * 100


def test_merge_fails_before_writing_when_no_volume_has_capacity(tmp_path, monkeypatch):
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    (inputs / 'outcomes.jsonl').write_text('evidence')
    volume = tmp_path / 'volume'
    volume.mkdir()
    monkeypatch.setattr(shutil, 'disk_usage', lambda path: SimpleNamespace(free=1))
    with pytest.raises(RuntimeError, match='Insufficient graph merge space before writing'):
        storage_function()([inputs], [volume])
    assert list(volume.iterdir()) == []
