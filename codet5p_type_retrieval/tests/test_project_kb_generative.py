import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_DIR = ROOT / "Python"
PIPELINE_DIR = ROOT / "codet5p_type_retrieval"
sys.path.insert(0, str(PYTHON_DIR))

from project_kb import build_project_kb, top_project_types


def test_project_kb_contains_definitions_imports_returns_and_reexports(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    (project / "models.py").write_text(
        "from typing import TypeAlias\n"
        "from torch import Tensor as TorchTensor\n"
        "UserId: TypeAlias = str\n"
        "class User: pass\n"
        "def load() -> User:\n    return User()\n",
        encoding="utf-8",
    )
    imports = tmp_path / "imports"
    imports.mkdir()
    (imports / "torch.json").write_text(json.dumps([{
        "type": "class", "kind": "class", "name": "Tensor",
        "qualified_name": "torch.Tensor", "module": "torch",
        "definition": "class Tensor: pass", "source": "third_party",
    }]), encoding="utf-8")

    kb = build_project_kb(project, imports)
    kinds = {(item["name"], item["kind"]) for item in kb["records"]}

    assert ("User", "class") in kinds
    assert ("UserId", "type_alias") in kinds
    assert ("TorchTensor", "reexport_alias") in kinds
    assert ("load", "function") in kinds
    assert ("User", "function_return") in kinds
    assert ("Tensor", "class") in kinds


def test_top_project_types_never_uses_candidate_outside_project_kb(tmp_path):
    kb = {
        "records": [{
            "name": "LocalType", "qualified_name": "app.LocalType",
            "kind": "class", "source": "project",
            "definition": "class LocalType: pass",
        }]
    }
    ranked = top_project_types(
        kb, "value", "value = ForeignType()",
        [{"name": "ForeignType", "qualified_name": "shared.ForeignType"}],
        limit=10,
    )
    assert [item["name"] for item in ranked] == ["LocalType"]


def test_generative_preprocess_writes_tagged_input_and_exact_label(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "owner__repo.jsonl").write_text(json.dumps({
        "id": "one", "url": "https://github.com/owner/repo",
        "split": "train", "scope": "arg", "name": "value", "loc": "predict@12",
        "gttype": "torch.Tensor",
        "interprocedural_slice": "def predict(value: <mask>): return value",
        "recommendation_types": [{
            "name": f"Type{i}", "qualified_name": f"pkg.Type{i}",
            "definition": f"class Type{i}: pass",
        } for i in range(12)],
    }) + "\n", encoding="utf-8")
    output = tmp_path / "output"

    subprocess.run([
        sys.executable, str(PIPELINE_DIR / "preprocess_generative.py"),
        "--input", str(raw), "--output-dir", str(output),
    ], check=True)
    row = json.loads((output / "train.jsonl").read_text(encoding="utf-8"))

    assert row["label"] == "torch.Tensor"
    assert row["target_function"] == "predict"
    assert row["target_scope"] == "arg"
    assert len(row["recommendation_types"]) == 10
    for tag in (
        "[TARGET_NAME]", "[TARGET_FUNCTION]", "[TARGET_SCOPE]",
        "[INTERPROCEDURAL_SLICE]",
        "[RECOMMENDATION_TYPES]", "[TYPE]", "[DEFINITION]",
    ):
        assert tag in row["input"]
    assert "candidates" not in row
