import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK_DIR = ROOT / "kaggle_notebooks"
sys.path.insert(0, str(NOTEBOOK_DIR))

import commit_shard_versions
import commit_merge_finalize
import generate_notebooks
import recover_shard_version


def source_with_tag(notebook, tag):
    cells = [
        cell
        for cell in notebook["cells"]
        if tag in cell.get("metadata", {}).get("tags", [])
    ]
    assert len(cells) == 1
    return cells[0]["source"]


def test_standalone_notebook_locks_publish_owner_and_single_shard():
    notebook = generate_notebooks.shard_notebook(
        0,
        10,
        "https://github.com/duyvu1105/TypePro.git",
        "main",
        assigned_shards=[0],
        expected_dataset_owner="duyvu1105",
    )
    serialized = json.dumps(notebook)
    config = source_with_tag(notebook, "typepro-shard-config")

    assert "ASSIGNED_SHARDS = [0]" in config
    assert "SHARD_INDEX = 0" in config
    assert "EXPECTED_DATASET_OWNER = 'duyvu1105'" in config
    assert "TYPEPRO_PUBLISH_USERNAME" in serialized
    assert "TYPEPRO_PUBLISH_KEY" in serialized
    assert "Kaggle notebook host" in serialized
    assert "use_explicit_credential" in serialized
    assert 'os.environ[\\"KAGGLE_USERNAME\\"] = publish_username' in serialized
    assert "credentials_printed" in serialized
    assert "SLICE_ANNOTATION_TIMEOUT_SECONDS = 120" in config
    assert "PACKAGE_DOWNLOAD_TIMEOUT_SECONDS = 30" in config
    assert "KB_PHASE_TIMEOUT_SECONDS = 300" in config
    assert "PROJECT_ANALYSIS_TIMEOUT_SECONDS = 300" in config
    assert "SLICE_INDEX_TIMEOUT_SECONDS = 1800" in config
    assert "SLICE_TRACE_EVERY = 10" in config
    assert 'RETRIEVAL_SCHEMA_VERSION = "typepro-project-kb-top10-generative-v2"' in config
    assert "INCLUDE_BUILTINS = True" in config
    assert "INCLUDE_RETURNS = True" in config
    assert "--slice-annotation-timeout-seconds" in serialized
    assert "--package-download-timeout-seconds" in serialized
    assert "--kb-phase-timeout-seconds" in serialized
    assert "--project-analysis-timeout-seconds" in serialized
    assert "--slice-index-timeout-seconds" in serialized
    assert "--slice-trace-every" in serialized
    assert "--slice-timeout-project" not in serialized
    assert "--retrieval-schema-version" in serialized
    assert "restored_runtime.get" in serialized
    assert notebook["metadata"]["typepro"] == {
        "assigned_shards": [0],
        "initial_shard_index": 0,
        "expected_dataset_owner": "duyvu1105",
        "public_dataset": False,
    }


@pytest.mark.parametrize("shard_index", range(10))
def test_rendered_version_contains_exactly_one_assigned_shard(shard_index):
    template = generate_notebooks.shard_notebook(
        shard_index,
        10,
        "https://github.com/duyvu1105/TypePro.git",
        "main",
        assigned_shards=[shard_index],
        expected_dataset_owner="duyvu1105" if shard_index < 5 else "duymign",
        public_dataset=shard_index >= 5,
    )
    rendered = commit_shard_versions.render_shard_version(
        template,
        shard_index,
        (shard_index,),
        "duyvu1105" if shard_index < 5 else "duymign",
        shard_index >= 5,
    )
    config = source_with_tag(rendered, "typepro-shard-config")

    assert f"SHARD_INDEX = {shard_index}" in config
    assert rendered["metadata"]["typepro"]["rendered_shard_index"] == shard_index
    assert rendered["metadata"]["typepro"]["version_contract"] == (
        "one-kaggle-notebook-builds-one-shard"
    )


def test_render_rejects_shard_owned_by_other_account():
    template = generate_notebooks.shard_notebook(
        0,
        10,
        "https://github.com/duyvu1105/TypePro.git",
        "main",
        assigned_shards=[0],
        expected_dataset_owner="duyvu1105",
    )
    with pytest.raises(ValueError, match="not assigned"):
        commit_shard_versions.render_shard_version(
            template,
            5,
            (0,),
            "duyvu1105",
            False,
        )


def test_render_split_partition_uses_physical_modulo_coordinates():
    template = generate_notebooks.shard_notebook(
        1,
        10,
        "https://github.com/duyvu1105/TypePro.git",
        "main",
        assigned_shards=[1],
        expected_dataset_owner="duyvu1105",
    )
    rendered = commit_shard_versions.render_shard_version(
        template,
        1,
        (1,),
        "duyvu1105",
        False,
        physical_shard_index=11,
        physical_shard_count=30,
    )
    config = source_with_tag(rendered, "typepro-shard-config")

    assert "ASSIGNED_SHARDS = [11]" in config
    assert "SHARD_INDEX = 11" in config
    assert "SHARD_COUNT = 30" in config


def test_plan_requires_ten_notebooks_and_five_shards_per_account(tmp_path):
    shards_plan = []
    for account, shards in (("duyvu1105", range(5)), ("duymign", range(5, 10))):
        for shard_index in shards:
            notebook_name = f"shard-{shard_index:02d}.ipynb"
            (tmp_path / notebook_name).write_text("{}", encoding="utf-8")
            shards_plan.append({
                "shard_index": shard_index,
                "part_count": generate_notebooks.SHARD_PART_COUNTS.get(shard_index, 1),
                "runner_account": account,
                "dataset_owner": account,
                "public_dataset": account == "duymign",
                "notebook": notebook_name,
                "kernel_slug": f"typepro-python-shard-{shard_index:02d}",
            })
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps({
            "schema_version": "typepro-shard-account-plan-v3",
            "final_dataset_owner": "duyvu1105",
            "shard_count": 10,
            "shards": shards_plan,
        }),
        encoding="utf-8",
    )

    owner, count, plans = commit_shard_versions.load_plan(plan_path)
    assert owner == "duyvu1105"
    assert count == 10
    assert [plan.runner_account for plan in plans[:5]] == ["duyvu1105"] * 5
    assert [plan.runner_account for plan in plans[5:]] == ["duymign"] * 5
    assert [index for plan in plans for index in plan.assigned_shards] == list(range(10))


def test_generated_artifacts_are_ten_standalone_notebooks_and_partitioned_merge():
    owner, count, plans = commit_shard_versions.load_plan(
        NOTEBOOK_DIR / "shard_account_plan.json"
    )

    assert owner == "duyvu1105"
    assert count == 10
    assert len(plans) == 10
    assert [plan.notebook_path.name for plan in plans] == [
        f"{index + 1:02d}_typepro_shard_{index:02d}.ipynb"
        for index in range(10)
    ]
    assert len({plan.kernel_slug for plan in plans}) == 10
    assert [plan.part_count for plan in plans] == [1, 1, 2, 3, 1, 1, 1, 2, 1, 3]
    for index, plan in enumerate(plans):
        notebook = json.loads(plan.notebook_path.read_text(encoding="utf-8"))
        config = source_with_tag(notebook, "typepro-shard-config")
        assert f"ASSIGNED_SHARDS = [{index}]" in config
        assert f"SHARD_INDEX = {index}" in config
        assert "SHARD_COUNT = 10" in config

    assert (NOTEBOOK_DIR / "11_merge_finalize.ipynb").exists()
    assert (NOTEBOOK_DIR / "12_train_and_infer.ipynb").exists()
    assert not (NOTEBOOK_DIR / "03_merge_finalize.ipynb").exists()
    assert not (NOTEBOOK_DIR / "04_train_and_infer.ipynb").exists()


def test_plan_rejects_private_non_final_account(tmp_path):
    shards_plan = []
    for account, shards in (("duyvu1105", range(5)), ("duymign", range(5, 10))):
        for shard_index in shards:
            notebook_name = f"shard-{shard_index:02d}.ipynb"
            (tmp_path / notebook_name).write_text("{}", encoding="utf-8")
            shards_plan.append({
                "shard_index": shard_index,
                "part_count": generate_notebooks.SHARD_PART_COUNTS.get(shard_index, 1),
                "runner_account": account,
                "dataset_owner": account,
                "public_dataset": False,
                "notebook": notebook_name,
                "kernel_slug": f"typepro-python-shard-{shard_index:02d}",
            })
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps({
            "schema_version": "typepro-shard-account-plan-v3",
            "final_dataset_owner": "duyvu1105",
            "shard_count": 10,
            "shards": shards_plan,
        }),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="other account's shards must be public"):
        commit_shard_versions.load_plan(plan_path)


def test_credential_must_belong_to_planned_runner(tmp_path):
    credential = tmp_path / "kaggle.json"
    credential.write_text(
        json.dumps({"username": "duymign", "key": "not-printed"}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="expected 'duyvu1105'"):
        commit_shard_versions.load_credential(credential, "duyvu1105")


def test_kernel_metadata_is_private_cpu_notebook():
    plan = commit_shard_versions.AccountPlan(
        runner_account="duymign",
        dataset_owner="duymign",
        public_dataset=True,
        notebook_path=Path("template.ipynb"),
        kernel_slug="typepro-python-shard-05",
        assigned_shards=(5,),
    )
    metadata = commit_shard_versions.kernel_metadata(plan, "typepro_shard.ipynb")
    assert metadata["id"] == "duymign/typepro-python-shard-05"
    assert metadata["title"] == "TypePro Python Shard 05"
    assert metadata["is_private"] is True
    assert metadata["enable_gpu"] is False
    assert metadata["enable_internet"] is True


def test_split_kernel_metadata_targets_existing_shard_slug():
    plan = commit_shard_versions.AccountPlan(
        runner_account="duyvu1105",
        dataset_owner="duyvu1105",
        public_dataset=False,
        notebook_path=Path("template.ipynb"),
        kernel_slug="typepro-python-shard-01",
        assigned_shards=(1,),
        part_count=3,
    )

    metadata = commit_shard_versions.kernel_metadata(
        plan, "typepro_shard.ipynb", part_index=1
    )

    assert metadata["id"] == "duyvu1105/typepro-python-shard-01"
    assert metadata["title"] == "TypePro Python Shard 01"


def test_merge_notebook_uses_attached_inputs_and_final_owner_for_publish():
    shard_accounts = [
        {
            "runner_account": "duyvu1105",
            "dataset_owner": "duyvu1105",
            "public_dataset": False,
            "assigned_shards": [0, 1, 2, 3, 4],
        },
        {
            "runner_account": "duymign",
            "dataset_owner": "duymign",
            "public_dataset": True,
            "assigned_shards": [5, 6, 7, 8, 9],
        },
    ]
    notebook = generate_notebooks.merge_notebook(
        10,
        "https://github.com/duyvu1105/TypePro.git",
        "main",
        expected_dataset_owner="duyvu1105",
        shard_accounts=shard_accounts,
    )
    serialized = json.dumps(notebook)

    assert "TYPEPRO_FINAL_USERNAME" in serialized
    assert "TYPEPRO_FINAL_KEY" in serialized
    assert "Kaggle notebook host" in serialized
    assert 'os.environ[\\"KAGGLE_USERNAME\\"] = final_username' in serialized
    assert "use_credential(FINAL_SOURCE)" in serialized
    assert 'item[\\"dataset_id\\"]' in serialized
    assert "FINAL_SOURCE['owner']" in serialized
    assert "/kaggle/input" in serialized
    assert '\\"datasets\\", \\"download\\"' not in serialized
    assert "INPUT_ROOT.rglob(\\\"shard_manifest.json\\\")" in serialized
    assert "dataset_id.rsplit" not in serialized
    assert "project_kb" in serialized
    assert "typepro-python-generative" in serialized
    assert "shutil.rmtree(MERGED_BUILD, ignore_errors=True)" in serialized


def test_merge_kernel_metadata_attaches_exact_merge_plan_inputs():
    dataset_ids = commit_merge_finalize.merge_dataset_ids()
    metadata = commit_merge_finalize.kernel_metadata("typepro_merge_finalize.ipynb")

    assert len(dataset_ids) == 16
    assert len(set(dataset_ids)) == 16
    assert metadata["id"] == "duyvu1105/merge-dataset"
    assert metadata["dataset_sources"] == dataset_ids


def test_train_notebook_uses_generative_model_not_contrastive_retrieval():
    serialized = json.dumps(generate_notebooks.train_notebook(
        "https://github.com/duyvu1105/TypePro.git", "main"
    ))

    assert "train_generative.py" in serialized
    assert "infer_generative.py" in serialized
    assert "typepro-codet5p-generative-project-kb-v2" in serialized
    assert "projection-dim" not in serialized
    assert 'PIPELINE_DIR / \\"train.py\\"' not in serialized
    assert "TOKEN LENGTH STATISTICS (NO TRUNCATION)" in serialized
    assert "average_tokens" in serialized
    assert "min_tokens" in serialized
    assert "max_tokens" in serialized
    assert serialized.index("TOKEN LENGTH STATISTICS") < serialized.index(
        "train_generative.py"
    )


def test_train_kernel_metadata_attaches_final_dataset(tmp_path):
    import commit_train_notebook

    metadata = commit_train_notebook.kernel_metadata("typepro_train_and_infer.ipynb")
    assert metadata["id"] == "duyvu1105/typepro-python-train-and-infer"
    assert metadata["enable_gpu"] is True
    assert metadata["enable_internet"] is True
    assert metadata["dataset_sources"] == ["duyvu1105/typepro-python-generative"]

    commit_train_notebook.write_payload(tmp_path)
    assert (tmp_path / "typepro_train_and_infer.ipynb").exists()
    assert (tmp_path / "kernel-metadata.json").exists()


def test_kernel_push_rejects_invalid_dataset_sources(tmp_path, monkeypatch):
    result = subprocess.CompletedProcess(
        args=["kaggle", "kernels", "push"],
        returncode=0,
        stdout="The following are not valid dataset sources and could not be added",
    )
    monkeypatch.setattr(commit_shard_versions.subprocess, "run", lambda *args, **kwargs: result)

    with pytest.raises(RuntimeError, match="Kaggle kernel push failed"):
        commit_shard_versions.run_push(
            tmp_path,
            {"username": "duyvu1105", "key": "redacted"},
            tmp_path,
        )


def test_merge_plan_covers_all_logical_shards_without_overlap():
    plan = json.loads(
        (NOTEBOOK_DIR / "shard_merge_plan.json").read_text(encoding="utf-8")
    )
    datasets = generate_notebooks.validate_merge_datasets(
        plan["datasets"], 10, "duyvu1105"
    )

    assert len(datasets) == 16
    assert {(item["shard_index"], item["shard_count"]) for item in datasets} == {
        (0, 10), (1, 10), (2, 20), (12, 20),
        (3, 30), (13, 30), (23, 30), (4, 10),
        (5, 10), (6, 10), (7, 20), (17, 20), (8, 10),
        (9, 30), (19, 30), (29, 30),
    }


def test_recovery_notebook_only_restores_and_publishes_completed_shard():
    notebook = generate_notebooks.recovery_notebook(
        8,
        10,
        "https://github.com/duyvu1105/TypePro.git",
        "main",
        expected_dataset_owner="duymign",
        public_dataset=True,
        source_kernel="duymign/typepro-python-shard-08/9",
    )
    serialized = json.dumps(notebook)

    assert 'SHARD_INDEX = 8' in serialized
    assert 'expected_archive = f\\"typepro_build_shard_' in serialized
    assert "publish_shard.py" in serialized
    assert "prepare_dataset.py" not in serialized
    assert "kernels" in serialized
    assert "source_handle" in serialized
    assert 'os.environ[\\"KAGGLE_USERNAME\\"] = EXPECTED_DATASET_OWNER' in serialized
    assert "PUBLISH_PUBLIC = True" in serialized


def test_recovery_metadata_pins_exact_source_version():
    plan = commit_shard_versions.AccountPlan(
        runner_account="duymign",
        dataset_owner="duymign",
        public_dataset=True,
        notebook_path=Path("template.ipynb"),
        kernel_slug="typepro-python-shard-08",
        assigned_shards=(8,),
    )
    metadata = recover_shard_version.recovery_metadata(
        plan, 8, 9, "recover_shard.ipynb"
    )

    assert metadata["id"] == "duymign/typepro-recover-shard-08-from-v9"
    assert metadata["kernel_sources"] == []
    assert metadata["enable_gpu"] is False
