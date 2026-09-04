import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_utils import (
    JsonlDataset,
    canonical_type_name,
    get_project,
    is_builtin_annotation,
    json_preview,
    normalize_recommendations,
    print_jsonl_samples,
    recommendations_from_prompt,
    select_training_samples,
)


def test_extracts_multiple_declarations_from_typepro_prompt():
    prompt = """The possible types analyzed from the import information are:
class Response:
    text: str
class Request:
    url: str
The code you need to make a prediction is:
x: <mask> = get()
"""
    result = recommendations_from_prompt(prompt)
    assert [item["name"] for item in result] == ["Response", "Request"]


def test_reads_direct_recommendation_objects_and_deduplicates():
    result = normalize_recommendations({
        "recommendation_types": [
            {"name": "pkg.Response", "definition": "class Response: pass"},
            {"name": "Response", "definition": "class Response: pass"},
        ]
    })
    assert len(result) == 1
    assert canonical_type_name("typing.pkg.Response") == "response"


def test_preserves_detailed_third_party_candidate_metadata():
    result = normalize_recommendations({
        "recommendation_types": [{
            "name": "Tensor",
            "qualified_name": "torch.Tensor",
            "package": "torch",
            "source": "third_party",
            "definition": "class Tensor:\n    # package: torch",
        }]
    })
    assert result[0]["qualified_name"] == "torch.Tensor"
    assert result[0]["package"] == "torch"


def test_builtin_filter_prefers_dataset_category():
    assert is_builtin_annotation({"scope": "arg", "cat": "builtins", "gttype": "list[int]"})
    assert not is_builtin_annotation({"scope": "arg", "cat": "user-defined", "gttype": "Tensor"})


def test_project_keeps_github_owner_and_repository():
    assert get_project({"url": "https://github.com/owner/repository/"}) == "owner/repository"


def test_jsonl_dataset_indexes_without_loading_all_rows():
    path = Path(__file__).with_name("fixture.jsonl")
    dataset = JsonlDataset(path)
    assert len(dataset) == 2
    assert dataset[1]["id"] == 2
    assert dataset[0]["id"] == 1


def test_training_sample_selection_is_deterministic_and_optional():
    rows = list(range(20))

    first = select_training_samples(rows, sample_count=5, seed=13)
    second = select_training_samples(rows, sample_count=5, seed=13)

    assert select_training_samples(rows, sample_count=None, seed=13) is rows
    assert [first[index] for index in range(len(first))] == [
        second[index] for index in range(len(second))
    ]
    assert len(first) == 5


def test_training_sample_selection_rejects_invalid_counts():
    import pytest

    with pytest.raises(ValueError, match="greater than 0"):
        select_training_samples([1, 2], sample_count=0, seed=13)
    with pytest.raises(ValueError, match="exceeds"):
        select_training_samples([1, 2], sample_count=3, seed=13)


def test_notebook_previews_are_bounded_and_stream_jsonl(capsys):
    rendered = json_preview({"query": "x" * 100}, max_chars=20)
    assert "truncated" in rendered

    path = Path(__file__).with_name("fixture.jsonl")
    print_jsonl_samples(path, sample_count=1, max_chars=0, title="train")
    output = capsys.readouterr().out
    assert "[samples] train #1" in output
    assert '"id": 1' in output
    assert '"id": 2' not in output
