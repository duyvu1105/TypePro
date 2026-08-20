import json
import os
import sys
import zipfile
from pathlib import Path

import pytest


PIPELINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE_DIR))

import kaggle_dataset_utils
from kaggle_dataset_utils import publish_dataset, validate_dataset_id, write_metadata
from publish_kaggle import archive_project_kb
from publish_shard import package_shard


def make_shard(tmp_path: Path) -> Path:
    work = tmp_path / "typepro_build_shard_00"
    (work / "metadata").mkdir(parents=True)
    (work / "raw_slices").mkdir()
    (work / "project_status").mkdir()
    (work / "project_kb" / "owner__repo").mkdir(parents=True)
    (work / "third_party_kb" / "dataset").mkdir(parents=True)
    manifest = {
        "shard_index": 0,
        "shard_count": 10,
        "selected_projects": 1,
        "attempted_projects": 1,
        "missing_projects": [],
    }
    (work / "shard_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (work / "runtime_manifest.json").write_text("{}", encoding="utf-8")
    (work / "metadata" / "split_manifest.json").write_text("{}", encoding="utf-8")
    (work / "raw_slices" / "owner__repo.jsonl").write_text("{}\n", encoding="utf-8")
    (work / "project_status" / "owner__repo.json").write_text("{}", encoding="utf-8")
    (work / "project_status" / "owner__repo.log").write_text("large log", encoding="utf-8")
    (work / "project_kb" / "owner__repo" / "knowledge_base.json").write_text(
        '{"schema_version":"typepro-project-kb-v1","records":[]}', encoding="utf-8"
    )
    # This is the exact class of collision that previously made Kaggle reject
    # the Dataset. Build-time KB files must not enter the published archive.
    (work / "third_party_kb" / "dataset" / "Cython.json").write_text("{}", encoding="utf-8")
    (work / "third_party_kb" / "dataset" / "cython.json").write_text("{}", encoding="utf-8")
    return work


def test_dataset_id_uses_authenticated_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("KAGGLE_USERNAME", "another-account")
    monkeypatch.setenv("KAGGLE_KEY", "secret")
    assert validate_dataset_id("another-account/typepro-build-shard-00") == (
        "another-account",
        "typepro-build-shard-00",
    )
    path = write_metadata(
        tmp_path,
        "another-account/typepro-build-shard-00",
        "TypePro Python shard 00 of 10",
    )
    assert json.loads(path.read_text(encoding="utf-8"))["id"] == (
        "another-account/typepro-build-shard-00"
    )


def test_publish_kaggle_archives_project_kb(tmp_path):
    data = tmp_path / "final"
    kb = data / "project_kb" / "owner__repo"
    kb.mkdir(parents=True)
    (kb / "knowledge_base.json").write_text('{"records": []}', encoding="utf-8")
    (data / "train.jsonl").write_text("{}\n", encoding="utf-8")

    archive = archive_project_kb(data)

    assert archive.name == "project_kb.zip"
    assert not (data / "project_kb").exists()
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.namelist() == ["owner__repo/knowledge_base.json"]
    assert (data / "train.jsonl").exists()


def test_dataset_id_accepts_kaggle_notebook_host_auth(monkeypatch):
    monkeypatch.setenv("KAGGLE_USERNAME", "another-account")
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    monkeypatch.delenv("KAGGLE_API_TOKEN", raising=False)

    assert validate_dataset_id("another-account/typepro-build-shard-00") == (
        "another-account",
        "typepro-build-shard-00",
    )


def test_dataset_id_rejects_null_or_mismatched_owner(monkeypatch):
    monkeypatch.setenv("KAGGLE_USERNAME", "another-account")
    monkeypatch.setenv("KAGGLE_KEY", "secret")
    with pytest.raises(ValueError, match="null Kaggle owner"):
        validate_dataset_id("/typepro-build-shard-00")
    with pytest.raises(RuntimeError, match="does not match authenticated account"):
        validate_dataset_id("duyvu1105/typepro-build-shard-00")


@pytest.mark.parametrize(
    ("dataset_exists", "existing_state", "expected_operation"),
    [(False, None, "create"), (True, "failed", "version")],
)
def test_publish_selects_create_or_repair_version(
    tmp_path,
    monkeypatch,
    dataset_exists,
    existing_state,
    expected_operation,
):
    monkeypatch.setenv("KAGGLE_USERNAME", "another-account")
    monkeypatch.setenv("KAGGLE_KEY", "secret")
    (tmp_path / "payload.zip").write_bytes(b"zip")
    commands = []

    class Result:
        returncode = 0
        stdout = "accepted"

    monkeypatch.setattr(kaggle_dataset_utils.shutil, "which", lambda _: "kaggle")
    monkeypatch.setattr(
        kaggle_dataset_utils,
        "_owned_dataset_exists",
        lambda _: dataset_exists,
    )
    monkeypatch.setattr(
        kaggle_dataset_utils,
        "_status",
        lambda _: (
            pytest.fail("must not query status before creating a new Dataset")
            if existing_state is None
            else (existing_state, existing_state)
        ),
    )
    monkeypatch.setattr(
        kaggle_dataset_utils,
        "_run",
        lambda command: commands.append(command) or Result(),
    )
    monkeypatch.setattr(kaggle_dataset_utils, "wait_for_status", lambda *args, **kwargs: "ready")

    publish_dataset(
        tmp_path,
        "another-account/typepro-build-shard-00",
        "TypePro Python shard 00 of 10",
        "completed",
    )
    assert commands[0][:3] == ["kaggle", "datasets", expected_operation]


def test_publish_rejects_cli_semantic_error_with_zero_exit(tmp_path, monkeypatch):
    monkeypatch.setenv("KAGGLE_USERNAME", "another-account")
    monkeypatch.setenv("KAGGLE_KEY", "secret")
    (tmp_path / "payload.zip").write_bytes(b"zip")

    class Result:
        returncode = 0
        stdout = "Dataset creation error: Dataset url's dataset slugs and hashlink are all null"

    monkeypatch.setattr(kaggle_dataset_utils.shutil, "which", lambda _: "kaggle")
    monkeypatch.setattr(kaggle_dataset_utils, "_owned_dataset_exists", lambda _: False)
    monkeypatch.setattr(
        kaggle_dataset_utils,
        "_status",
        lambda _: pytest.fail("must not query status before creating a new Dataset"),
    )
    monkeypatch.setattr(kaggle_dataset_utils, "_run", lambda command: Result())
    monkeypatch.setattr(
        kaggle_dataset_utils,
        "wait_for_status",
        lambda *args, **kwargs: pytest.fail("must not poll after Dataset registration failed"),
    )

    with pytest.raises(RuntimeError, match="hashlink are all null"):
        publish_dataset(
            tmp_path,
            "another-account/typepro-build-shard-00",
            "TypePro Python shard 00 of 10",
            "completed",
        )


def test_status_falls_back_to_files_when_legacy_endpoint_is_forbidden(monkeypatch):
    commands = []

    class Result:
        def __init__(self, returncode, stdout):
            self.returncode = returncode
            self.stdout = stdout

    results = iter([
        Result(1, "403 Client Error: Forbidden"),
        Result(0, "owner_test.json 221B"),
    ])
    monkeypatch.setattr(
        kaggle_dataset_utils,
        "_run",
        lambda command: commands.append(command) or next(results),
    )

    state, detail = kaggle_dataset_utils._status(
        "another-account/typepro-owner-test"
    )
    assert state == "ready"
    assert "owner_test.json" in detail
    assert commands[1][:3] == ["kaggle", "datasets", "files"]


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (
            "ref,title,size,lastUpdated\n"
            "another-account/typepro-build-shard-06,Shard 06,1000,2026-08-15\n",
            True,
        ),
        (
            "ref,title,size,lastUpdated\n"
            "another-account/typepro-build-shard-060,Other,1000,2026-08-15\n",
            False,
        ),
        ("No datasets found", False),
    ],
)
def test_owned_dataset_exists_requires_exact_ref(monkeypatch, output, expected):
    commands = []

    class Result:
        returncode = 0
        stdout = output

    monkeypatch.setattr(
        kaggle_dataset_utils,
        "_run",
        lambda command: commands.append(command) or Result(),
    )

    assert kaggle_dataset_utils._owned_dataset_exists(
        "another-account/typepro-build-shard-06"
    ) is expected
    assert commands == [[
        "kaggle",
        "datasets",
        "list",
        "--mine",
        "--search",
        "typepro-build-shard-06",
        "--csv",
    ]]


def test_package_contains_only_merge_inputs(tmp_path):
    work = make_shard(tmp_path)
    archive, manifest = package_shard(work, tmp_path / "payload")
    assert manifest["shard_count"] == 10
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    assert "typepro_build_shard_00/raw_slices/owner__repo.jsonl" in names
    assert "typepro_build_shard_00/project_status/owner__repo.json" in names
    assert "typepro_build_shard_00/project_kb/owner__repo/knowledge_base.json" in names
    assert not any("third_party_kb" in name for name in names)
    assert not any(name.endswith(".log") for name in names)
    assert len(names) == len({name.casefold() for name in names})


@pytest.mark.skipif(os.name == "nt", reason="Windows cannot create case-only filename pairs")
def test_package_rejects_case_insensitive_merge_collision(tmp_path):
    work = make_shard(tmp_path)
    (work / "raw_slices" / "OWNER__REPO.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Case-insensitive path collision"):
        package_shard(work, tmp_path / "payload")
