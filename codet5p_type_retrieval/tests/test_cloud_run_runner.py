import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from cloud_run.runner import (  # noqa: E402
    RETRIEVAL_SCHEMA_VERSION,
    safe_relative_object,
    shard_index_from_environment,
    validate_restored_schema,
)


def test_safe_relative_object_rejects_escape():
    assert safe_relative_object("runs/x/work/raw/a.jsonl", "runs/x/work/") == Path("raw/a.jsonl")
    with pytest.raises((ValueError, KeyError)):
        safe_relative_object("runs/other/secret", "runs/x/work/")


def test_task_coordinate_must_match_ten_shards(monkeypatch):
    monkeypatch.setenv("CLOUD_RUN_TASK_INDEX", "7")
    monkeypatch.setenv("CLOUD_RUN_TASK_COUNT", "10")
    assert shard_index_from_environment(None, 10) == 7
    monkeypatch.setenv("CLOUD_RUN_TASK_COUNT", "9")
    with pytest.raises(ValueError, match="expected 10"):
        shard_index_from_environment(None, 10)


def test_restore_schema_validation(tmp_path):
    validate_restored_schema(tmp_path)
    (tmp_path / "runtime_manifest.json").write_text(
        json.dumps({"retrieval_schema_version": RETRIEVAL_SCHEMA_VERSION}), encoding="utf-8"
    )
    validate_restored_schema(tmp_path)
    (tmp_path / "runtime_manifest.json").write_text(
        json.dumps({"retrieval_schema_version": "old"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="new TYPEPRO_RUN_ID"):
        validate_restored_schema(tmp_path)
