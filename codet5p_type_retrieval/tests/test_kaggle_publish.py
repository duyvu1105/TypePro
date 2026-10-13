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
from publish_shard import package_shard


def test_final_publisher_archives_project_kbs(tmp_path, monkeypatch):
    import publish_kaggle
    from types import SimpleNamespace

    for name in ("train.jsonl", "validation.jsonl", "test.jsonl", "manifest.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    kb = tmp_path / "project_kb" / "owner__repo"
    kb.mkdir(parents=True)
    (kb / "knowledge_base.json").write_text("{}", encoding="utf-8")
    args = SimpleNamespace(
        data_dir=str(tmp_path), dataset_id="duyvu1105/typepro-python-generative",
        title="TypePro Python Generative", message="Merge 19 shards", public=False,
    )
    monkeypatch.setattr(publish_kaggle, "parse_args", lambda: args)
    calls = []
    monkeypatch.setattr(publish_kaggle, "publish_dataset", lambda *a, **kw: calls.append(kw))
    publish_kaggle.main()
    assert calls == [{"public": False}]


@pytest.mark.parametrize('index', [12, 32])
def test_publish_subdivision_uses_isolated_dataset_slug(tmp_path, monkeypatch, index):
    import publish_shard
    from types import SimpleNamespace
    args = SimpleNamespace(work_dir=tmp_path, payload_dir=tmp_path / 'payload',
        expected_shard_index=index, expected_shard_count=40,
        dataset_id=f'duyvu1105/typepro-build-shard-{index}-of-40',
        title='Subdivision', message='Complete', public=False)
    monkeypatch.setattr(publish_shard, 'parse_args', lambda: args)
    monkeypatch.setattr(publish_shard, 'package_shard', lambda *a: (None, {'shard_index': index, 'shard_count': 40}))
    calls = []
    monkeypatch.setattr(publish_shard, 'publish_dataset', lambda *a, **kw: calls.append(a[1]))
    publish_shard.main()
    assert calls == [args.dataset_id]
    args.dataset_id = f'duyvu1105/typepro-build-shard-{index}'
    with pytest.raises(RuntimeError, match='slug'):
        publish_shard.main()


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


def test_v2_shard_publication_audits_before_packaging(tmp_path):
    from audit_context import POLICY, MASKING
    work = make_shard(tmp_path)
    (work / 'runtime_manifest.json').write_text(json.dumps({'context_policy_version': POLICY}), encoding='utf-8')
    row = {'context_policy_version': POLICY, 'target_masking_version': MASKING,
           'candidate_definition_max_chars': 8000,
           'recommendation_types': [{'name': 'C', 'definition': 'class C: pass'}]}
    raw = work / 'raw_slices' / 'owner__repo.jsonl'
    raw.write_text(json.dumps(row) + '\n', encoding='utf-8')
    archive, _ = package_shard(work, tmp_path / 'payload')
    with zipfile.ZipFile(archive) as bundle:
        assert 'typepro_build_shard_00/context_audit.json' in bundle.namelist()
    row['recommendation_types'][0]['definition'] = 'x' * 16001
    raw.write_text(json.dumps(row) + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='Unbounded'):
        package_shard(work, tmp_path / 'rejected')
    assert not (tmp_path / 'rejected').exists()


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
    ("dataset_exists", "existing_state", "expected_operation", "directory_mode"),
    [
        (False, None, "create", "skip"),
        (True, "failed", "version", "skip"),
        (True, "failed", "version", "zip"),
    ],
)
def test_publish_selects_create_or_repair_version(
    tmp_path,
    monkeypatch,
    dataset_exists,
    existing_state,
    expected_operation,
    directory_mode,
):
    monkeypatch.setenv("KAGGLE_USERNAME", "another-account")
    monkeypatch.setenv("KAGGLE_KEY", "secret")
    (tmp_path / "payload.zip").write_bytes(b"zip")
    commands = []

    class Result:
        returncode = 0
        stdout = "accepted"

    monkeypatch.setattr(kaggle_dataset_utils.shutil, "which", lambda _: "kaggle")
    monkeypatch.setattr(kaggle_dataset_utils, "_current_version", lambda _: 15)
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
        directory_mode=directory_mode,
    )
    assert commands[0][:3] == ["kaggle", "datasets", expected_operation]
    assert commands[0][commands[0].index("--dir-mode") + 1] == directory_mode


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

def test_final_packaging_preserves_case_colliding_kbs(tmp_path):
    from publish_kaggle import package_final
    source = tmp_path / 'source'
    payload = tmp_path / 'payload'
    for slug, text in [('Stra\u00dfe__Repo', 'first'), ('strasse__repo', 'second'), ('other__repo', 'third')]:
        kb = source / 'project_kb' / slug
        kb.mkdir(parents=True)
        (kb / 'knowledge_base.json').write_text(text)
    (source / 'train.jsonl').write_text('rows')
    index = package_final(source, payload)
    with zipfile.ZipFile(payload / 'project_kb.zip') as bundle:
        names = bundle.namelist()
        assert len(names) == len({name.casefold() for name in names}) == 3
        assert bundle.read(index['Stra\u00dfe__Repo'].removeprefix('project_kb/')) == b'first'
        assert bundle.read(index['strasse__repo'].removeprefix('project_kb/')) == b'second'
        # Simulate Kaggle extracting each ZIP under its filename stem.
        bundle.extractall(payload / 'project_kb')
    assert all((payload / relative).is_file() for relative in index.values())
    assert index['other__repo'] == 'project_kb/other__repo/knowledge_base.json'
    assert json.loads((payload / 'project_kb_index.json').read_text(encoding='utf-8')) == index
    assert (payload / 'train.jsonl').read_text() == 'rows'


def test_ready_old_version_is_not_publish_success(monkeypatch):
    monkeypatch.setattr(kaggle_dataset_utils, '_status', lambda _: ('ready', 'old version ready'))
    versions = iter([15, 15, 16])
    monkeypatch.setattr(kaggle_dataset_utils, '_current_version', lambda _: next(versions))
    sleeps = []
    monkeypatch.setattr(kaggle_dataset_utils.time, 'sleep', lambda _: sleeps.append(True))
    assert kaggle_dataset_utils.wait_for_status('owner/dataset', newer_than=15) == 'ready'
    assert len(sleeps) == 2


def test_ready_old_version_times_out(monkeypatch):
    monkeypatch.setattr(kaggle_dataset_utils, '_status', lambda _: ('ready', 'old ready'))
    monkeypatch.setattr(kaggle_dataset_utils, '_current_version', lambda _: 15)
    ticks = iter([0, 0, 0, 2])
    monkeypatch.setattr(kaggle_dataset_utils.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(kaggle_dataset_utils.time, 'sleep', lambda _: None)
    with pytest.raises(TimeoutError):
        kaggle_dataset_utils.wait_for_status('owner/dataset', newer_than=15, timeout_seconds=1)


def test_verify_cli_resolves_published_kb_index(tmp_path):
    import hashlib
    import subprocess
    project = 'AleNriG/Sims'
    row = {
        'project': project, 'split': 'train', 'target_name': 'x',
        'target_function': 'f', 'target_scope': 'arg', 'interprocedural_slice': 'x',
        'recommendation_types': [{'type': 'Item', 'definition': 'class Item: pass'}],
        'label': 'Item',
        'input': '[TARGET_NAME][TARGET_FUNCTION][TARGET_SCOPE][INTERPROCEDURAL_SLICE]'
                 '[RECOMMENDATION_TYPES][TYPE][DEFINITION]',
    }
    manifest = {'schema_version': 'typepro-codet5p-generative-project-kb-v2',
                'projects': {'knowledge_bases': 1}, 'output': {}}
    for split in ('train', 'validation', 'test'):
        path = tmp_path / f'{split}.jsonl'
        path.write_text(json.dumps(row) + '\n' if split == 'train' else '', encoding='utf-8')
        manifest['output'][split] = {'file': path.name, 'rows': int(split == 'train'),
                                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    relative = 'project_kb/AleNriG__Sims--unique/knowledge_base.json'
    kb = tmp_path / relative
    kb.parent.mkdir(parents=True)
    kb.write_text(json.dumps({'records': [{'name': 'Item'}]}))
    (tmp_path / 'project_kb_index.json').write_text(json.dumps({'AleNriG__Sims': relative}))
    command = [sys.executable, str(PIPELINE_DIR / 'verify_dataset.py'), '--data-dir', str(tmp_path)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"verified": true' in result.stdout
    kb.unlink()
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'missing project KB' in result.stderr
