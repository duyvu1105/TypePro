import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prepare_dataset import (
    annotation_timeout_for_project,
    build_splits,
    eligible_parameter_rows,
    matching_skip_pattern,
    parse_args,
    project_from_row,
    run_logged,
)


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
        "scope": "arg",
        "cat": "user-defined",
        "gttype": "Response",
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


def test_only_non_builtin_parameters_are_eligible():
    rows = [
        row("owner/repository", 1),
        {**row("owner/repository", 2), "scope": "return"},
        {**row("owner/repository", 3), "cat": "builtins", "gttype": "int"},
    ]
    eligible, stats = eligible_parameter_rows(rows)
    assert [item["name"] for item in eligible] == ["value_1"]
    assert stats["non_parameter"] == 1
    assert stats["builtin"] == 1


def test_annotation_timeout_is_limited_to_configured_slow_projects():
    projects = {"home-assistant/home-assistant", "Opentrons/opentrons"}

    assert annotation_timeout_for_project(600, projects, "home-assistant/home-assistant") == 600
    assert annotation_timeout_for_project(600, projects, "Opentrons/opentrons") == 600
    assert annotation_timeout_for_project(600, projects, "fast/project") == 0
    assert annotation_timeout_for_project(0, projects, "home-assistant/home-assistant") == 0


def test_annotation_timeout_applies_to_every_project_when_allowlist_is_empty():
    assert annotation_timeout_for_project(120, set(), "fast/project") == 120
    assert annotation_timeout_for_project(120, set(), "henne90gen/tower_defense") == 120


def test_slice_trace_defaults_to_every_annotation():
    with patch.object(sys, "argv", ["prepare_dataset.py"]):
        args = parse_args()

    assert args.slice_trace_every == 1
    assert args.skip_project == []
    assert args.package_download_timeout_seconds == 60
    assert args.kb_phase_timeout_seconds == 0
    assert args.project_analysis_timeout_seconds == 0


def test_run_logged_terminates_a_timed_out_phase(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        run_logged(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            tmp_path,
            tmp_path / "phase.log",
            timeout_seconds=0.1,
        )


def test_run_logged_hard_kills_annotation_when_soft_timeout_stalls(tmp_path):
    command = [
        sys.executable,
        "-u",
        "-c",
        (
            "import time; "
            "print('[export:annotation:start] index=1/1', flush=True); "
            "time.sleep(10)"
        ),
    ]

    with pytest.raises(subprocess.TimeoutExpired) as error:
        run_logged(
            command,
            tmp_path,
            tmp_path / "annotation.log",
            annotation_stall_timeout_seconds=0.1,
        )

    assert error.value.timeout == 0.1
    assert "[export:annotation:start]" in (error.value.output or "")


def test_skip_project_patterns_match_case_insensitive_owner_or_repository():
    patterns = ["F-shakalaka", "home-assistant"]

    assert (
        matching_skip_pattern("F-Shakalaka/example-project", patterns)
        == "F-shakalaka"
    )
    assert (
        matching_skip_pattern("home-assistant/home-assistant", patterns)
        == "home-assistant"
    )
    assert matching_skip_pattern("ocf/ocfweb", patterns) is None
