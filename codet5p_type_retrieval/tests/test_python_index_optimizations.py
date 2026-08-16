import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_DIR = ROOT / "Python"
sys.path.insert(0, str(PYTHON_DIR))

import readFunctionUseData
from export_slices import export_one
from function_methods import Function_methods
from type_defined import ProjectClassDefine, ProjectDefined, ProjectUseData


def make_methods() -> Function_methods:
    methods = Function_methods.__new__(Function_methods)
    methods.total_function_data = [
        ProjectDefined("exact", "first"),
        ProjectDefined("fallback", "fallback-first"),
        ProjectDefined("exact", "second"),
        ProjectDefined("fallback", "fallback-second"),
    ]
    methods.total_function_use_data = [
        ProjectUseData("exact", "call-1", 1, "a.py"),
        ProjectUseData("fallback", "call-2", 2, "b.py"),
        ProjectUseData("exact", "call-3", 3, "c.py"),
    ]
    methods.total_class_data = [
        ProjectClassDefine("Exact", "class Exact: first", "a.py"),
        ProjectClassDefine("Outer", "class Outer: first", "b.py"),
        ProjectClassDefine("Exact", "class Exact: second", "c.py"),
    ]
    methods._rebuild_indexes()
    return methods


def test_indexed_lookups_preserve_legacy_order_and_dotted_fallbacks():
    methods = make_methods()

    assert methods.get_target_name_signals("exact") == ["first", "second"]
    assert methods.get_target_name_signals("module.fallback") == [
        "fallback-first",
        "fallback-second",
    ]
    assert [item.source_code for item in methods.get_function_use_data("exact")] == [
        "call-1",
        "call-3",
    ]
    assert [
        item.source_code for item in methods.get_function_use_data("module.fallback")
    ] == ["call-2"]
    assert methods.get_class_by_names("Outer.Exact") == ["class Outer: first"]


def test_function_call_membership_set_matches_original_exact_name_semantics():
    readFunctionUseData.project_function_data = [
        ProjectDefined("alpha", ""),
        ProjectDefined("beta", ""),
        ProjectDefined("alpha", "duplicate"),
    ]
    readFunctionUseData.project_function_names = {
        item.name for item in readFunctionUseData.project_function_data
    }

    assert readFunctionUseData.is_project_function("alpha") is True
    assert readFunctionUseData.is_project_function("beta") is True
    assert readFunctionUseData.is_project_function("Alpha") is False
    assert readFunctionUseData.is_project_function("missing") is False


def test_shared_project_index_produces_identical_export_record(tmp_path, monkeypatch):
    project = tmp_path / "owner" / "project"
    project.mkdir(parents=True)
    source = project / "sample.py"
    source.write_text(
        "def target(value):\n    return value\n",
        encoding="utf-8",
    )
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    function_path = index_dir / "functions.json"
    use_path = index_dir / "uses.json"
    class_path = index_dir / "classes.json"
    function_path.write_text("[]", encoding="utf-8")
    use_path.write_text("[]", encoding="utf-8")
    class_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(Function_methods, "project_data_path", str(function_path))
    monkeypatch.setattr(Function_methods, "project_use_path", str(use_path))
    monkeypatch.setattr(Function_methods, "project_class_path", str(class_path))
    row = {
        "file": str(source),
        "url": "https://github.com/owner/project",
        "name": "value",
        "loc": "target@1",
        "scope": "arg",
        "gttype": "CustomType",
    }

    uncached = export_one(row, source)
    shared = export_one(row, source, function_methods=Function_methods())

    assert shared == uncached
