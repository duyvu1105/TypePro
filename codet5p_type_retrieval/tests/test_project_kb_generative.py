import json
import ast
import copy
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_DIR = ROOT / "Python"
PIPELINE_DIR = ROOT / "codet5p_type_retrieval"
sys.path.insert(0, str(PYTHON_DIR))

from project_kb import build_project_kb, target_member_query, top_project_types
from target_context import MASK


def test_project_kb_contains_definitions_imports_body_returns_and_reexports(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    (project / "models.py").write_text(
        "from typing import TypeAlias\n"
        "from torch import Tensor as TorchTensor\n"
        "UserId: TypeAlias = str\n"
        "class User: pass\n"
        "def load() -> User:\n    return User()\n"
        "def annotation_only() -> HiddenAnnotation:\n    return None\n",
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
    assert ("HiddenAnnotation", "function_return") not in kinds
    assert ("Tensor", "class") in kinds
    load = next(item for item in kb["records"] if item["name"] == "load" and item["kind"] == "function")
    assert "->" not in load["definition"]


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


def test_top_project_types_masks_target_before_candidate_scoring(tmp_path):
    orders = []
    for annotation in ("marker", "OtherGold"):
        project = tmp_path / annotation
        project.mkdir()
        (project / "app.py").write_text(
            "class A:\n"
            f"    def target(self, value: {annotation}):\n"
            "        pass\n"
            "class B:\n"
            "    marker = 1\n"
            "    def target(self, value):\n"
            "        pass\n",
            encoding="utf-8",
        )
        kb = build_project_kb(project)
        before = copy.deepcopy(kb)
        ranked = top_project_types(
            kb, "value", "def target(self, value: <mask>):\n    return marker",
            target_function="target", target_scope="arg", limit=2,
        )
        assert kb == before
        class_a = next(item for item in ranked if item["name"] == "A")
        assert annotation not in class_a["definition"]
        assert MASK in class_a["definition"]
        orders.append([item["name"] for item in ranked])

    assert orders[0] == orders[1] == ["B", "A"]


def test_target_member_matching_uses_target_receiver_and_inheritance(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "app.py"
    source.write_text(
        "class BaseDebugger:\n"
        "    def debug_with(self, code): pass\n"
        "    @property\n"
        "    def target_pid(self): return 1\n"
        "class Debugger(BaseDebugger): pass\n"
        "class Distractor:\n"
        "    def unrelated(self): pass\n"
        "def inspect(debugger: HiddenGold):\n"
        "    alias = debugger\n"
        "    alias.debug_with('code')\n"
        "    other = Distractor()\n"
        "    other.unrelated()\n"
        "    return debugger.target_pid\n",
        encoding="utf-8",
    )
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
    query = target_member_query(function, "debugger")
    kb = build_project_kb(project)

    assert query == {"methods": ["debug_with"], "attributes": ["target_pid"]}
    debugger = next(item for item in kb["records"] if item.get("name") == "Debugger")
    assert {"debug_with", "target_pid"} <= set(debugger["members"])
    ranked = top_project_types(
        kb, "debugger", "def inspect(debugger: <mask>): pass", limit=3,
        target_function="inspect", target_scope="arg", target_members=query,
    )
    assert [item["name"] for item in ranked[:2]] == ["BaseDebugger", "Debugger"]


def test_target_member_matching_is_annotation_invariant(tmp_path):
    outputs = []
    for annotation in ("HiddenGoldA", "HiddenGoldB"):
        project = tmp_path / annotation
        project.mkdir()
        source = project / "app.py"
        source.write_text(
            "class Client:\n"
            "    def send(self, payload): pass\n"
            f"def consume(client: {annotation}):\n"
            "    return client.send('value')\n",
            encoding="utf-8",
        )
        tree = ast.parse(source.read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
        query = target_member_query(function, "client")
        kb = build_project_kb(project)
        ranked = top_project_types(
            kb, "client", "def consume(client: <mask>): return client.send('value')",
            target_function="consume", target_scope="arg", target_members=query,
        )
        outputs.append((query, [(item["name"], item["definition"]) for item in ranked]))

    assert outputs[0] == outputs[1]


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
