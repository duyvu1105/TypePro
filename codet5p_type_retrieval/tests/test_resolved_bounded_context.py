"""Regression checks for ambiguous callees and oversized recommendations."""
import ast
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'Python'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ast_context_slicer import FunctionCatalog, CANDIDATE_DEFINITION_MAX_CHARS
from export_slices import export_one
from function_methods import Function_methods
from project_index import scan_project
from project_kb import build_project_kb, top_project_types
from preprocess_generative import normalized_recommendations


def catalog_for(tmp_path, sources):
    for name, source in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
    parsed, _ = scan_project(tmp_path)
    return FunctionCatalog(parsed)


@pytest.mark.parametrize('prefix,call,expected', [
    ('from helper import convert as cv', 'cv(value)', 'helper.convert'),
    ('import helper as h', 'h.convert(value)', 'helper.convert'),
    ('import helper', 'helper.convert(value)', 'helper.convert'),
    ('from missing import convert', 'convert(value)', None),
    ('', 'obj.convert(value)', None),
    ('', 'convert(value)', None),
    ('from helper import convert\nconvert = other', 'convert(value)', None),
    ('if flag:\n from helper import convert', 'convert(value)', None),
])
def test_only_explicit_unshadowed_imports_resolve(tmp_path, prefix, call, expected):
    cat = catalog_for(tmp_path, {
        'app.py': prefix + '\ndef target(value):\n return ' + call + '\n',
        'helper.py': 'def convert(item: str):\n return item\n',
        'other.py': 'def convert(item):\n return 99\n',
    })
    tree = cat.trees[str((tmp_path / 'app.py').resolve())]
    caller = tree.body[-1]
    record, reason = cat.resolve(caller.body[0].value, tmp_path / 'app.py', caller)
    assert (record[1] if record else None) == expected
    assert bool(reason) == (expected is None)


@pytest.mark.parametrize('shadow', [
    'convert = value', 'import other as convert', 'def convert(x): return x',
    'try:\n pass\nexcept Exception as convert:\n pass',
])
def test_local_shadowing_never_uses_global_callee(tmp_path, shadow):
    cat = catalog_for(tmp_path, {'app.py': 'def convert(x): return x\ndef target(value):\n ' + shadow.replace('\n', '\n ') + '\n return convert(value)\n'})
    caller = cat.trees[str((tmp_path / 'app.py').resolve())].body[-1]
    assert cat.resolve(caller.body[-1].value, tmp_path / 'app.py', caller)[0] is None


def test_relative_import_is_scoped_to_the_package(tmp_path):
    cat = catalog_for(tmp_path, {'pkg/app.py': 'from .helper import convert\ndef target(x): return convert(x)\n',
                                 'pkg/helper.py': 'def convert(x): return x\n'})
    caller = cat.trees[str((tmp_path / 'pkg/app.py').resolve())].body[-1]
    assert cat.resolve(caller.body[0].value, tmp_path / 'pkg/app.py', caller)[0][1] == 'pkg.helper.convert'


def test_thousands_of_same_name_methods_do_not_enter_slice(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / 'app.py'
    path.write_text('def target(adapter: HiddenGold, value):\n return adapter.serialize(value)\n', encoding='utf-8')
    # More definitions than the reported production failure, with annotated bodies.
    (tmp_path / 'models.py').write_text(''.join(
        f'class Model{i}:\n def serialize(self, value: str): return value\n def deserialize(self, value: str): return value\n'
        for i in range(2400)), encoding='utf-8')
    parsed, _ = scan_project(tmp_path)
    methods = Function_methods.from_parsed(tmp_path, parsed)
    row = {'scope': 'arg', 'name': 'adapter', 'loc': 'target@1', 'gttype': 'HiddenGold'}
    result = export_one(row, path, function_methods=methods, project_kb={'records': []})
    text = result['interprocedural_slice']
    assert 'adapter.serialize(value)' in text
    assert 'def serialize' not in text and 'def deserialize' not in text
    assert len(text) < 500
    assert 'HiddenGold' not in text


@pytest.mark.parametrize('size', [15999, 16000, 16001, 430474])
def test_definition_boundaries_and_unicode_preserve_kb(size):
    prefix, suffix = 'class Parser:\n    text = "', '"\n'
    definition = prefix + '\u03bb' * (size - len(prefix) - len(suffix)) + suffix
    kb = {'records': [{'name': 'Parser', 'qualified_name': 'app.Parser', 'kind': 'class',
                       'source': 'project', 'definition': definition, 'members': []}]}
    before = copy.deepcopy(kb)
    candidate = top_project_types(kb, 'parser', 'parser')[0]
    assert candidate['definition'] == definition[:16000]
    assert kb == before
    assert candidate['definition_reduction']['output_chars'] == min(len(definition), 16000)


def test_preprocessing_caps_all_ten_definitions_without_changing_ranking():
    rows = [{'name': f'Type{i}', 'qualified_name': f'app.Type{i}', 'definition': 'x' * 17000} for i in range(12)]
    result = normalized_recommendations({'recommendation_types': rows}, 10)
    assert [r['type'] for r in result] == [f'Type{i}' for i in range(10)]
    assert all(len(r['definition']) == CANDIDATE_DEFINITION_MAX_CHARS for r in result)
    assert all(len(r['definition']) == 17000 for r in rows)


def test_caller_context_excludes_unresolved_same_name_calls(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cat = catalog_for(tmp_path, {'app.py': '''def target(value: HiddenGold):
 return value
def caller():
 actual = 7
 return target(actual)
def unrelated(obj):
 wrong = 'noise'
 return obj.target(wrong)
'''})
    parsed, _ = scan_project(tmp_path)
    methods = Function_methods.from_parsed(tmp_path, parsed)
    result = export_one({'scope': 'arg', 'name': 'value', 'loc': 'target@1', 'gttype': 'HiddenGold'}, tmp_path / 'app.py', function_methods=methods, project_kb={'records': []})
    assert 'actual = 7' in result['interprocedural_slice']
    assert 'wrong' not in result['interprocedural_slice']
    assert 'obj.target' not in result['interprocedural_slice']


def test_imported_standalone_function_can_resolve_inside_a_method(tmp_path):
    cat = catalog_for(tmp_path, {'app.py': 'from helper import convert\nclass C:\n def run(self, value): return convert(value)\n',
                                 'helper.py': 'def convert(item): return item\n'})
    caller = cat.trees[str((tmp_path / 'app.py').resolve())].body[-1].body[0]
    assert cat.resolve(caller.body[0].value, tmp_path / 'app.py', caller)[0][1] == 'helper.convert'


@pytest.mark.parametrize('mutation', ['helper.convert = other', 'setattr(helper, "convert", other)', 'globals()["helper"] = other'])
def test_monkeypatch_or_dynamic_scope_does_not_prove_callee(tmp_path, mutation):
    cat = catalog_for(tmp_path, {'app.py': 'import helper\ndef target(value):\n ' + mutation + '\n return helper.convert(value)\n',
                                 'helper.py': 'def convert(item): return item\n'})
    caller = cat.trees[str((tmp_path / 'app.py').resolve())].body[-1]
    assert cat.resolve(caller.body[-1].value, tmp_path / 'app.py', caller)[0] is None


def test_audit_rejects_unbounded_or_unproven_output(tmp_path):
    from audit_context import audit, POLICY, MASKING, MAX_DEFINITION_CHARS
    from preprocess_generative import CANDIDATE_DEFINITION_MAX_CHARS as PREPROCESS_MAX
    assert MAX_DEFINITION_CHARS == PREPROCESS_MAX == CANDIDATE_DEFINITION_MAX_CHARS
    row = {'context_policy_version': POLICY, 'target_masking_version': MASKING,
           'candidate_definition_max_chars': 16000,
           'recommendation_types': [{'name': 'C', 'definition': 'x' * 16000}],
           'recommendation_diagnostics': {'context_reduction': []},
           'interprocedural_slice': 'def f(value): return value', 'name': 'value',
           'target_function': 'f', 'scope': 'arg'}
    path = tmp_path / 'project.jsonl'
    def save():
        path.write_text(json.dumps(row) + '\n', encoding='utf-8')
    save()
    report = audit(tmp_path)
    assert report['verified'] and report['rows'] == 1
    row['recommendation_types'][0]['definition'] += 'x'
    save()
    with pytest.raises(ValueError, match='Unbounded'):
        audit(tmp_path)
    row['recommendation_types'][0]['definition'] = 'class C: pass'
    row['recommendation_diagnostics']['context_reduction'] = [{'callee': 'other.f', 'mode': 'full_fallback'}]
    save()
    with pytest.raises(ValueError, match='Unproven'):
        audit(tmp_path)


@pytest.mark.parametrize('where', ['caller_module', 'callee_module', 'lambda', 'missing_scope'])
def test_opaque_lexical_or_module_effects_fail_closed(tmp_path, where):
    app = 'import helper\ndef target(value):\n return helper.convert(value)\n'
    helper = 'def convert(value): return value\n'
    if where == 'caller_module':
        app += 'exec(code)\n'
    elif where == 'callee_module':
        helper += 'globals()["convert"] = replacement\n'
    elif where == 'lambda':
        app = 'import helper\ndef target(value):\n return (lambda helper: helper.convert(value))(value)\n'
    cat = catalog_for(tmp_path, {'app.py': app, 'helper.py': helper})
    caller = cat.trees[str((tmp_path / 'app.py').resolve())].body[1]
    call = next(n for n in ast.walk(caller) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute))
    assert cat.resolve(call, tmp_path / 'app.py', None if where == 'missing_scope' else caller)[0] is None
