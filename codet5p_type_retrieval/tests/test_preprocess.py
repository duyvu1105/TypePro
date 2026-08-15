import json
import sys
from pathlib import Path


PIPELINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE_DIR))

import preprocess


def test_ground_truth_policy_keeps_missing_recommendation_as_positive(tmp_path, monkeypatch, capsys):
    raw = tmp_path / "raw.jsonl"
    rows = [
        {
            "id": "one",
            "url": "https://github.com/owner/repo",
            "split": "train",
            "scope": "arg",
            "name": "tensor",
            "gttype": "Tensor",
            "interprocedural_slice": "def f(tensor: <mask>): ...",
            "recommendation_types": [{
                "name": "Array",
                "definition": "class Array: pass",
                "package": "arraylib",
                "source": "third_party",
            }],
        },
        {
            "id": "two",
            "url": "https://github.com/owner/repo",
            "split": "train",
            "scope": "arg",
            "name": "array",
            "gttype": "Array",
            "interprocedural_slice": "def g(array: <mask>): ...",
            "recommendation_types": [{
                "name": "Array",
                "definition": "class Array: pass",
                "package": "arraylib",
                "source": "third_party",
            }, {
                "name": "Tensor",
                "definition": "class Tensor: pass",
                "package": "tensorlib",
                "source": "third_party",
            }],
        },
    ]
    raw.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    output = tmp_path / "processed"
    monkeypatch.setattr(sys, "argv", [
        "preprocess.py",
        "--input", str(raw),
        "--output-dir", str(output),
        "--positive-policy", "ground-truth",
        "--preview-samples", "0",
        "--log-every", "0",
    ])
    preprocess.main()
    first = json.loads((output / "train.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first["label"] == "Tensor"
    assert first["candidates"][0]["name"] == "Tensor"
    assert first["candidates"][0]["is_positive"] is True
    assert first["candidates"][0]["source"] == "ground_truth"
    output_text = capsys.readouterr().out
    assert "[ground-truth-in-recommendation-types]" in output_text
    assert "train: 1/2 samples (50.00%)" in output_text
    assert "validation: 0/0 samples (0.00%)" in output_text
    assert "test: 0/0 samples (0.00%)" in output_text


def test_recommendation_coverage_uses_all_checked_samples_as_denominator():
    stats = preprocess.Counter({
        "train_gold_recommended": 3,
        "train_gold_not_recommended": 1,
        "validation_gold_recommended": 1,
        "validation_gold_not_recommended": 2,
    })

    coverage = preprocess.recommendation_coverage(stats)

    assert coverage["train"] == {
        "total_samples": 4,
        "ground_truth_in_recommendation_types": 3,
        "ground_truth_not_in_recommendation_types": 1,
        "percentage": 75.0,
    }
    assert coverage["validation"]["percentage"] == 33.33
    assert coverage["test"]["percentage"] == 0.0
