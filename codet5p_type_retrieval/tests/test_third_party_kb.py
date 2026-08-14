import json
import sys
from pathlib import Path


PYTHON_DIR = Path(__file__).resolve().parents[2] / "Python"
sys.path.insert(0, str(PYTHON_DIR))

from build_third_party_kb import discover_imports, scan_package
from import_analyzer import importAnalyzer


def test_discovers_imports_and_extracts_structural_class_definition(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text(
        "from tensorlib import Tensor\nimport os\n",
        encoding="utf-8",
    )
    imports, _ = discover_imports(project)
    assert imports == {"tensorlib", "os"}

    package = tmp_path / "tensorlib"
    package.mkdir()
    (package / "__init__.pyi").write_text(
        "class Tensor(BaseTensor):\n"
        "    shape: tuple[int, ...]\n"
        "    dtype: str\n"
        "    def reshape(self, *shape: int) -> Tensor: ...\n",
        encoding="utf-8",
    )
    records, stats = scan_package(
        "tensorlib", [package], max_files=10, max_members=20, max_chars=4000,
    )
    tensor = next(item for item in records if item["type"] == "class")
    assert tensor["qualified_name"] == "tensorlib.Tensor"
    assert tensor["bases"] == ["BaseTensor"]
    assert "shape: tuple[int, ...]" in tensor["definition"]
    assert "def reshape" in tensor["definition"]
    assert stats["classes"] == 1

    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "tensorlib.json").write_text(json.dumps(records), encoding="utf-8")
    monkeypatch.setenv("TYPEPRO_THIRD_PARTY_DATASET", str(kb))
    analyzer = importAnalyzer(str(project / "app.py"))
    recommendations = analyzer.get_class_recommendations("input_tensor")
    assert recommendations
    assert "class Tensor(BaseTensor):" in recommendations[0]
    structural = analyzer.calculate_similarity_for_class("def f(x):\n    return x.reshape(2, 2)")
    assert any("class Tensor(BaseTensor):" in value for value in structural)
