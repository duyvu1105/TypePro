import json
import sys
from pathlib import Path


PYTHON_DIR = Path(__file__).resolve().parents[2] / "Python"
sys.path.insert(0, str(PYTHON_DIR))

import build_third_party_kb
from build_third_party_kb import discover_imports, scan_package, typeshed_roots
from import_analyzer import importAnalyzer
from export_slices import recommendation_objects


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


def test_scanner_keeps_private_classes_aliases_and_stdlib_provenance(tmp_path):
    package = tmp_path / "pathlib"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from typing import TypeAlias\n"
        "class Path: pass\n"
        "class _InternalPath: pass\n"
        "PathLike: TypeAlias = str | bytes\n",
        encoding="utf-8",
    )

    records, stats = scan_package(
        "pathlib", [package], max_files=10, max_members=20, max_chars=4000,
        source_kind="stdlib",
    )

    assert {item["name"] for item in records} == {
        "Path", "_InternalPath", "PathLike"
    }
    assert stats["private_classes"] == 1
    assert stats["aliases"] == 1
    assert all(item["source"] == "stdlib" for item in records)
    exported = recommendation_objects(item["definition"] for item in records)
    assert {item["source"] for item in exported} == {"stdlib"}


def test_exact_import_and_qualified_attribute_precede_fuzzy_candidates(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "app.py"
    source.write_text(
        "from tensorlib.core import Tensor\n"
        "import tensorlib.core as tc\n"
        "value = tc.Batch()\n",
        encoding="utf-8",
    )
    kb = tmp_path / "kb"
    kb.mkdir()
    records = []
    for name in ["Tensor", "Batch", *[f"Candidate{i}" for i in range(12)]]:
        records.append({
            "type": "class",
            "name": name,
            "package": "tensorlib",
            "module": "tensorlib.core",
            "qualified_name": f"tensorlib.core.{name}",
            "definition": f"class {name}:\n    # package: tensorlib\n    # module: tensorlib.core",
            "source": "third_party",
        })
    (kb / "tensorlib.json").write_text(json.dumps(records), encoding="utf-8")
    monkeypatch.setenv("TYPEPRO_THIRD_PARTY_DATASET", str(kb))

    analyzer = importAnalyzer(str(source))
    exact = analyzer.get_exact_import_recommendations()
    fuzzy = analyzer.get_class_recommendations("candidate", limit=20)
    inventory = analyzer.get_imported_module_inventory("batch")

    assert "class Tensor:" in exact[0]
    assert any("class Batch:" in item for item in exact)
    assert len(fuzzy) > 5
    assert any("class Batch:" in item for item in inventory)


def test_exact_import_fallback_adds_symbols_without_reading_masked_annotation(
    tmp_path, monkeypatch
):
    source = tmp_path / "app.py"
    source.write_text(
        "from datetime import datetime\n"
        "import pathlib\n"
        "def target(value: pathlib.Path): return value\n",
        encoding="utf-8",
    )
    kb = tmp_path / "kb"
    kb.mkdir()
    monkeypatch.setenv("TYPEPRO_THIRD_PARTY_DATASET", str(kb))
    analyzer = importAnalyzer(str(source))

    exact = analyzer.get_exact_import_recommendations(
        "from datetime import datetime\n"
        "import pathlib\n"
        "def target(value: <mask>):\n    return value\n"
    )

    names = {item["name"] for item in recommendation_objects(exact)}
    assert "datetime" in names
    assert "Path" not in names


def test_typeshed_root_discovers_stdlib_and_third_party_stubs(tmp_path):
    typeshed = tmp_path / "typeshed"
    (typeshed / "stdlib" / "pathlib").mkdir(parents=True)
    (typeshed / "stdlib" / "pathlib" / "__init__.pyi").write_text(
        "class Path: ...\n", encoding="utf-8"
    )
    package = typeshed / "stubs" / "requests" / "requests"
    package.mkdir(parents=True)
    (package / "__init__.pyi").write_text(
        "class Session: ...\n", encoding="utf-8"
    )

    assert typeshed_roots("pathlib", [str(typeshed)]) == [
        (typeshed / "stdlib" / "pathlib").resolve()
    ]
    assert typeshed_roots("requests", [str(typeshed)]) == [package.resolve()]


def test_stdlib_runtime_is_not_scanned_when_typeshed_exists(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("import pathlib\n", encoding="utf-8")
    typeshed = tmp_path / "typeshed"
    stub = typeshed / "stdlib" / "pathlib"
    stub.mkdir(parents=True)
    (stub / "__init__.pyi").write_text("class Path: ...\n", encoding="utf-8")
    output = tmp_path / "kb"
    summary_path = tmp_path / "summary.json"

    def reject_runtime_scan(_import_name):
        raise AssertionError("installed stdlib roots must not be inspected")

    monkeypatch.setattr(build_third_party_kb, "installed_roots", reject_runtime_scan)
    monkeypatch.setattr(build_third_party_kb, "bundled_typeshed_paths", lambda: [])
    monkeypatch.setattr(sys, "argv", [
        "build_third_party_kb.py",
        "--project-root", str(project),
        "--output-dir", str(output),
        "--download-cache", str(tmp_path / "downloads"),
        "--typeshed-root", str(typeshed),
        "--summary-output", str(summary_path),
        "--no-download-missing",
    ])

    build_third_party_kb.main()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    package = summary["packages"]["pathlib"]
    assert package["source"] == "typeshed"
    assert package["runtime_stdlib_skipped"] is True
