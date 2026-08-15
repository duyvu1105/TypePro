import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK_DIR = ROOT / "kaggle_notebooks"
sys.path.insert(0, str(NOTEBOOK_DIR))

import commit_shard_versions
import generate_notebooks


def source_with_tag(notebook, tag):
    cells = [
        cell
        for cell in notebook["cells"]
        if tag in cell.get("metadata", {}).get("tags", [])
    ]
    assert len(cells) == 1
    return cells[0]["source"]


def test_account_notebook_locks_publish_owner_and_assigned_shards():
    notebook = generate_notebooks.shard_notebook(
        0,
        10,
        "https://github.com/duyvu1105/TypePro.git",
        "main",
        assigned_shards=[0, 1, 2, 3, 4],
        expected_dataset_owner="duyvu1105",
    )
    serialized = json.dumps(notebook)
    config = source_with_tag(notebook, "typepro-shard-config")

    assert "ASSIGNED_SHARDS = [0, 1, 2, 3, 4]" in config
    assert "SHARD_INDEX = 0" in config
    assert "EXPECTED_DATASET_OWNER = 'duyvu1105'" in config
    assert "TYPEPRO_PUBLISH_USERNAME" in serialized
    assert "TYPEPRO_PUBLISH_KEY" in serialized
    assert "Kaggle notebook host" in serialized
    assert "use_explicit_credential" in serialized
    assert 'os.environ[\\"KAGGLE_USERNAME\\"] = publish_username' in serialized
    assert "credentials_printed" in serialized
    assert notebook["metadata"]["typepro"] == {
        "assigned_shards": [0, 1, 2, 3, 4],
        "initial_shard_index": 0,
        "expected_dataset_owner": "duyvu1105",
        "public_dataset": False,
    }


@pytest.mark.parametrize("shard_index", [0, 1, 2, 3, 4])
def test_rendered_version_contains_exactly_one_assigned_shard(shard_index):
    template = generate_notebooks.shard_notebook(
        0,
        10,
        "https://github.com/duyvu1105/TypePro.git",
        "main",
        assigned_shards=[0, 1, 2, 3, 4],
        expected_dataset_owner="duyvu1105",
    )
    rendered = commit_shard_versions.render_shard_version(
        template,
        shard_index,
        (0, 1, 2, 3, 4),
        "duyvu1105",
        False,
    )
    config = source_with_tag(rendered, "typepro-shard-config")

    assert f"SHARD_INDEX = {shard_index}" in config
    assert rendered["metadata"]["typepro"]["rendered_shard_index"] == shard_index
    assert rendered["metadata"]["typepro"]["version_contract"] == (
        "one-kaggle-version-builds-one-shard"
    )


def test_render_rejects_shard_owned_by_other_account():
    template = generate_notebooks.shard_notebook(
        0,
        10,
        "https://github.com/duyvu1105/TypePro.git",
        "main",
        assigned_shards=[0, 1, 2, 3, 4],
        expected_dataset_owner="duyvu1105",
    )
    with pytest.raises(ValueError, match="not assigned"):
        commit_shard_versions.render_shard_version(
            template,
            5,
            (0, 1, 2, 3, 4),
            "duyvu1105",
            False,
        )


def test_plan_requires_two_accounts_and_exact_ten_shards(tmp_path):
    notebooks = []
    accounts = []
    for account, shards in (("duyvu1105", range(5)), ("duymign", range(5, 10))):
        notebook_name = f"{account}.ipynb"
        (tmp_path / notebook_name).write_text("{}", encoding="utf-8")
        notebooks.append(notebook_name)
        accounts.append({
            "runner_account": account,
            "dataset_owner": account,
            "public_dataset": account == "duymign",
            "notebook": notebook_name,
            "assigned_shards": list(shards),
            "kernel_slug": f"typepro-shards-{min(shards):02d}-{max(shards):02d}",
        })
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps({
            "schema_version": "typepro-shard-account-plan-v2",
            "final_dataset_owner": "duyvu1105",
            "shard_count": 10,
            "accounts": accounts,
        }),
        encoding="utf-8",
    )

    owner, count, plans = commit_shard_versions.load_plan(plan_path)
    assert owner == "duyvu1105"
    assert count == 10
    assert [plan.runner_account for plan in plans] == ["duyvu1105", "duymign"]
    assert [index for plan in plans for index in plan.assigned_shards] == list(range(10))


def test_plan_rejects_private_non_final_account(tmp_path):
    accounts = []
    for account, shards in (("duyvu1105", range(5)), ("duymign", range(5, 10))):
        notebook_name = f"{account}.ipynb"
        (tmp_path / notebook_name).write_text("{}", encoding="utf-8")
        accounts.append({
            "runner_account": account,
            "dataset_owner": account,
            "public_dataset": False,
            "notebook": notebook_name,
            "assigned_shards": list(shards),
            "kernel_slug": f"typepro-shards-{min(shards):02d}-{max(shards):02d}",
        })
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps({
            "schema_version": "typepro-shard-account-plan-v2",
            "final_dataset_owner": "duyvu1105",
            "shard_count": 10,
            "accounts": accounts,
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
        kernel_slug="typepro-shards-05-09",
        assigned_shards=(5, 6, 7, 8, 9),
    )
    metadata = commit_shard_versions.kernel_metadata(plan, "typepro_shard.ipynb")
    assert metadata["id"] == "duymign/typepro-shards-05-09"
    assert metadata["is_private"] is True
    assert metadata["enable_gpu"] is False
    assert metadata["enable_internet"] is True


def test_merge_notebook_switches_private_dataset_credentials_by_owner():
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
    assert "source['owner']" in serialized
    assert "FINAL_SOURCE['owner']" in serialized
