"""Files absent from a project index still export masked, local evidence."""
import ast
import json
import sys
from pathlib import Path

import pytest

from typepro.analysis.ast_context_slicer import FunctionCatalog
from typepro.analysis.export_slices import export_one
from typepro.analysis.function_methods import Function_methods
from typepro.analysis.export_slices import AnnotationTimeoutError
import typepro.analysis.export_slices as export_slices
@pytest.mark.parametrize('scope,name', [('arg', 'value'), ('return', 'target')])
@pytest.mark.parametrize('excluded', [False, True])
def test_export_missing_catalog_file(tmp_path, scope, name, excluded):
    path = tmp_path / 'venv' / 'app.py'
    path.parent.mkdir()
    path.write_text('''from typing import NewType
UserId = NewType('UserId', int)
def helper(value: str) -> str:
    """A useful local contract."""
    return value
def target(value: HiddenGold) -> HiddenGold:
    """A useful target docstring."""
    return helper(str(UserId(value)))
''', encoding='utf-8')
    methods = Function_methods.empty()
    if excluded:
        other = tmp_path / 'other.py'
        tree = ast.parse('def noise(): return 0')
        methods.context_catalog = FunctionCatalog([(other, 'other', '', tree)])
    original = getattr(methods, 'context_catalog', None)
    row = dict(scope=scope, name=name, loc='target@7')
    result = export_one(row, path, function_methods=methods, project_kb={'records': []})
    assert result is not None
    code = result['interprocedural_slice']
    assert '<mask>' in code
    assert 'A useful target docstring.' in code
    assert "NewType('UserId', int)" in code
    assert 'def helper(value: str)' in code
    # A file-local fallback belongs to this masked export, never the shared index.
    if original is not None:
        assert methods.context_catalog is original
        assert str(path.resolve()) not in original.trees
    first = code
    path.write_text(path.read_text(encoding='utf-8').replace('HiddenGold', 'DifferentGold'), encoding='utf-8')
    second = export_one(row, path, function_methods=methods, project_kb={'records': []})
    # The annotation outside the target slot is allowed; compare after normalizing it.
    assert first.replace('HiddenGold', 'DifferentGold') == second['interprocedural_slice']


def test_interrupted_caller_scan_is_not_cached(tmp_path, monkeypatch):
    path = tmp_path / 'app.py'
    tree = ast.parse('def target(x): return x\ntarget(1)\ntarget(2)')
    catalog = FunctionCatalog([(path, 'app', '', tree)])
    resolve = catalog.resolve
    calls = 0

    def interrupted(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise AnnotationTimeoutError('interrupt caller scan')
        return resolve(*args)

    monkeypatch.setattr(catalog, 'resolve', interrupted)
    with pytest.raises(AnnotationTimeoutError):
        catalog.callers('app.target')
    monkeypatch.setattr(catalog, 'resolve', resolve)
    assert len(catalog.callers('app.target')) == 2


def test_export_totals_distinguish_failures_and_continue(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / 'app.py'
    path.write_text('pass', encoding='utf-8')
    dataset = tmp_path / 'rows.json'
    names = ['empty', 'timeout', 'exception', 'success']
    dataset.write_text(json.dumps([{'file': str(path), 'name': name} for name in names]), encoding='utf-8')
    output = tmp_path / 'slices.jsonl'
    monkeypatch.setattr(sys, 'argv', ['export_slices', '--dataset', str(dataset),
                        '--repos-root', str(tmp_path), '--output', str(output)])
    monkeypatch.setattr(export_slices, 'Function_methods', Function_methods.empty)

    def export(row, *args, **kwargs):
        if row['name'] == 'empty':
            return None
        if row['name'] == 'timeout':
            raise AnnotationTimeoutError('deadline')
        if row['name'] == 'exception':
            raise KeyError('unavailable file')
        return {'recommendation_diagnostics': {'context_reduction': [
            {'component': 'catalog', 'mode': 'file_local'}]}}

    monkeypatch.setattr(export_slices, 'export_one', export)
    export_slices.main()
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert summary['written'] == 1
    assert summary['failed'] == 3
    assert summary['empty_slices'] == 1
    assert summary['timed_out'] == 1
    assert summary['exceptions_by_type'] == {'KeyError': 1}
    assert summary['local_catalog_fallbacks'] == 1
    assert len(output.read_text(encoding='utf-8').splitlines()) == 1


