import json
import sys
from pathlib import Path


PIPELINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE_DIR))

import preprocess


def test_ground_truth_policy_keeps_missing_recommendation_as_positive(tmp_path, monkeypatch):
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
