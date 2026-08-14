import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prepare_dataset import build_splits, project_from_row


class Args:
    split_profile = "paper_project"
    seed = 13
    validation_project_ratio = 0.20
    test_projects = 2


def row(project: str, number: int):
    return {
        "file": f"repos/{project}/module_{number}.py",
        "loc": "global@global",
        "name": f"value_{number}",
        "scope": "local",
        "gttype": "str",
    }


def test_project_from_typegen_path():
    assert project_from_row(row("owner/repository", 1)) == "owner/repository"


def test_paper_split_has_no_project_overlap():
    projects = [f"owner/repo{i}" for i in range(30)]
    train = [row(project, index) for index, project in enumerate(projects[:20])]
    test = [row(project, index + 100) for index, project in enumerate(projects[10:])]
    sampled = test[:5]
    values = {"trainset.json": train, "testset.json": test, "testset_randomsampled.json": sampled}
    with patch("prepare_dataset.read_json", side_effect=lambda path: values[path.name]):
        splits, _ = build_splits(Args(), Path("unused"))
    project_sets = [{project_from_row(item) for item in splits[split]} for split in ("train", "validation", "test")]
    assert project_sets[0].isdisjoint(project_sets[1])
    assert project_sets[0].isdisjoint(project_sets[2])
    assert project_sets[1].isdisjoint(project_sets[2])
