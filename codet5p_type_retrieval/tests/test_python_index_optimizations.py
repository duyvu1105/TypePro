import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PYTHON_DIR = ROOT / "Python"
sys.path.insert(0, str(PYTHON_DIR))

import export_slices
import readFunctionUseData
from export_slices import AnnotationTimeoutError, annotation_deadline, export_one
from function_methods import Function_methods
from slicing_code_class import CachedStatement, ProjectAnalysisCache, Slicer
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


def test_statement_index_and_result_cache_preserve_exact_output(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text(
        "import pathlib\n"
        "seed = make_seed()\n"
        "value = seed + 1\n"
        "if value:\n"
        "    consume(value)\n"
        "result = wrap(value)\n",
        encoding="utf-8",
    )
    methods = make_methods()
    uncached = Slicer(str(source), function_methods=methods)
    cache = ProjectAnalysisCache(file_limit=4, statement_limit=20, use_limit=20)
    cached = Slicer(str(source), function_methods=methods, analysis_cache=cache)

    expected = uncached.find_statements_for_var(str(source), "value", True)
    expected_seed = uncached.find_statements_for_var(str(source), "seed", True)
    first = cached.find_statements_for_var(str(source), "value", True)
    different_variable = cached.find_statements_for_var(str(source), "seed", True)
    second = cached.find_statements_for_var(str(source), "value", True)

    assert first == expected
    assert different_variable == expected_seed
    assert second == expected
    assert cache.misses["file"] == 1
    assert cache.hits["file"] >= 1
    assert cache.hits["statement"] == 1
    structure = cache.file_analysis(str(source))
    assert all(
        isinstance(statement, CachedStatement)
        for statements in structure.values()
        for statement in statements
    )


def test_shared_analysis_cache_preserves_records_for_repeated_function_uses(
    tmp_path, monkeypatch
):
    project = tmp_path / "owner" / "project"
    project.mkdir(parents=True)
    source = project / "sample.py"
    source.write_text(
        "def target(first, second):\n"
        "    return first or second\n"
        "\n"
        "left = build_left()\n"
        "right = build_right()\n"
        "target(left, right)\n",
        encoding="utf-8",
    )
    methods = make_methods()
    methods.total_function_use_data = [
        ProjectUseData("target", "target(left, right)", 7, str(source))
    ]
    methods._rebuild_indexes()
    monkeypatch.setattr(
        Function_methods, "project_data_path", str(tmp_path / "unused-functions.json")
    )
    rows = [
        {
            "file": str(source),
            "url": "https://github.com/owner/project",
            "name": name,
            "loc": "target@1",
            "scope": "arg",
            "gttype": "CustomType",
        }
        for name in ("first", "second")
    ]

    expected = [export_one(row, source, function_methods=methods) for row in rows]
    cache = ProjectAnalysisCache()
    actual = [
        export_one(
            row,
            source,
            function_methods=methods,
            analysis_cache=cache,
        )
        for row in rows
    ]

    assert actual == expected
    assert cache.hits["function"] == 1
    assert cache.hits["function_output"] == 1
    assert cache.hits["analyzer"] == 1


def test_function_use_cache_preserves_event_order_and_signature_filtering(
    tmp_path, monkeypatch
):
    source = tmp_path / "sample.py"
    source.write_text("def target(value):\n    return value\n", encoding="utf-8")
    methods = make_methods()
    uses = [
        ProjectUseData("target", "first()", 1, str(source)),
        ProjectUseData("target", "second()", 2, str(source)),
    ]
    methods.total_function_use_data = uses
    methods._rebuild_indexes()
    cache = ProjectAnalysisCache()
    slicer = Slicer(str(source), function_methods=methods, analysis_cache=cache)
    parsed = {
        uses[0]: (["call-1", "shared"], ["excluded", "sig-1"]),
        uses[1]: (["excluded", "call-2"], ["sig-1", "sig-2"]),
    }
    calls = []

    def fake_parse(use):
        calls.append(use)
        return parsed[use]

    monkeypatch.setattr(slicer, "parse_use_data", fake_parse)

    first = slicer.function_use_data("target", ["excluded"])
    second = slicer.function_use_data("target", ["excluded"])

    assert first == ["sig-1", "call-1", "shared", "sig-2", "excluded", "call-2"]
    assert second == first
    assert calls == uses
    assert cache.hits["function"] == 1
    assert cache.hits["function_output"] == 1


def test_annotation_deadline_raises_and_always_cancels_timer(monkeypatch):
    assert not issubclass(AnnotationTimeoutError, Exception)
    handlers = {}
    timers = []
    alarm = 14
    old_handler = object()

    monkeypatch.setattr(export_slices.signal, "SIGALRM", alarm, raising=False)
    monkeypatch.setattr(export_slices.signal, "ITIMER_REAL", 0, raising=False)
    monkeypatch.setattr(
        export_slices.signal, "getsignal", lambda _signal_number: old_handler
    )

    def fake_signal(signal_number, handler):
        handlers[signal_number] = handler

    def fake_setitimer(_timer, seconds):
        timers.append(seconds)

    monkeypatch.setattr(export_slices.signal, "signal", fake_signal)
    monkeypatch.setattr(export_slices.signal, "setitimer", fake_setitimer, raising=False)

    with pytest.raises(AnnotationTimeoutError, match="600-second"):
        with annotation_deadline(600):
            handlers[alarm](alarm, None)

    assert timers == [600, 0]
    assert handlers[alarm] is old_handler
