import ast
import copy
import sys
from pathlib import Path

import pytest

from typepro.analysis.ast_context_slicer import bind_arguments, reduce_class, reduce_function, FunctionCatalog
from typepro.analysis.export_slices import export_one
from typepro.analysis.function_methods import Function_methods
from typepro.analysis.project_index import scan_project
from typepro.analysis.project_kb import build_project_kb, top_project_types
from typepro.analysis.target_context import mask_definition


def function(source):
    return ast.parse(source).body[0]


def test_target_reduction_keeps_alias_mutation_and_removes_literal_noise():
    original = function('def f(value):\n unused = 123\n alias = value\n result = []\n result.append(alias)\n return result\n')
    reduced = reduce_function(original, ['value'])
    code = ast.unparse(reduced.node)
    assert reduced.mode == 'sliced'
    assert 'unused' not in code
    assert 'result.append(alias)' in code
    assert 'alias = value' in code
    assert 'unused' in ast.unparse(original)


def test_control_flow_keeps_none_and_exception_paths():
    original = function('def f(x):\n unused = 42\n if x is None:\n  return\n try:\n  return x[0]\n except IndexError:\n  return None\n finally:\n  x.clear()\n')
    code = ast.unparse(reduce_function(original, returns=True).node)
    assert 'unused' not in code
    assert 'return None' in code and 'finally:' in code and 'return\n' in code


@pytest.mark.parametrize('statement', ['exec(code)', 'def nested():\n  return 1'])
def test_opaque_effects_fall_back(statement):
    original = function('def f(value):\n ' + statement.replace('\n', '\n ') + '\n return value\n')
    reduced = reduce_function(original, ['value'])
    assert reduced.mode == 'full_fallback'
    assert ast.dump(original) == ast.dump(reduced.node)


@pytest.mark.parametrize('call,expected', [
    ('f(a,b)', {'path': 'a', 'content': 'b', 'flag': 'False'}),
    ('f(content=b,path=a)', {'path': 'a', 'content': 'b', 'flag': 'False'}),
    ('f(a,content=b,flag=True)', {'path': 'a', 'content': 'b', 'flag': 'True'}),
    ('f(*(a,b))', {'path': 'a', 'content': 'b', 'flag': 'False'}),
    ('f(**{"path": a, "content": b})', {'path': 'a', 'content': 'b', 'flag': 'False'}),
])
def test_binding_without_keyword_syntax(call, expected):
    bound, reason = bind_arguments(function('def f(path,content,*,flag=False): pass'), ast.parse(call).body[0].value)
    assert not reason
    assert {k: ast.unparse(v) for k, v in bound.items()} == expected


@pytest.mark.parametrize('call', ['f(*values)', 'f(**options)', 'f(a,b,path=c)', 'f(a)', 'f(**{"path": a, "path": b})'])
def test_unknown_or_invalid_binding_does_not_guess(call):
    bound, reason = bind_arguments(function('def f(path,content): pass'), ast.parse(call).body[0].value)
    assert bound is None and reason


def test_posonly_and_keywordonly_rules():
    signature = function('def f(x,/,*,y): pass')
    assert bind_arguments(signature, ast.parse('f(1,y=2)').body[0].value)[0] is not None
    assert bind_arguments(signature, ast.parse('f(x=1,y=2)').body[0].value)[0] is None


def test_catalog_same_name_shadowing_is_not_certain(tmp_path):
    a = tmp_path / 'a.py'
    b = tmp_path / 'b.py'
    a.write_text('def helper(value): return value\ndef caller(helper,value): return helper(value)\n')
    b.write_text('def helper(value): return value\n')
    parsed, _ = scan_project(tmp_path)
    catalog = FunctionCatalog(parsed)
    caller = ast.parse(a.read_text()).body[1]
    matches, certain = catalog.lookup(caller.body[0].value, a, caller)
    assert matches == [] and not certain


CLASS = '''class Client:
    VERSION = 1
    UNUSED = 9
    def __init__(self, transport):
        self.transport = transport
        self.history = []
    def fetch(self):
        return self._request(self.VERSION)
    def _request(self, version):
        return self.transport.request(version)
    def clear_history(self):
        self.history.clear()
'''


def test_class_selects_dependency_closure_and_preserves_whole_methods():
    text, diag = reduce_class(CLASS, {'methods': ['fetch']})
    assert diag['mode'] == 'sliced'
    assert 'clear_history' not in text and 'UNUSED' not in text
    assert 'self.history = []' in text  # Entire selected constructor survives.
    before = {n.name: n for n in ast.parse(CLASS).body[0].body if isinstance(n, ast.FunctionDef)}
    after = {n.name: n for n in ast.parse(text).body[0].body if isinstance(n, ast.FunctionDef)}
    for name, node in after.items():
        assert ast.dump(node) == ast.dump(before[name])


@pytest.mark.parametrize('query', [{}, {'methods': ['missing']}])
def test_class_no_matching_evidence_keeps_whole_class(query):
    text, diag = reduce_class(CLASS, query)
    assert text == CLASS and diag['mode'] == 'full_fallback'


def test_unknown_method_decorator_falls_back_and_constructor_keeps_new():
    text = 'class C:\n @register()\n def unrelated(self): pass\n def fetch(self): return 1\n'
    assert reduce_class(text, {'methods': ['fetch']})[1]['reason'] == 'method_decorator'
    text = 'class C:\n def __new__(cls): return object.__new__(cls)\n def __init__(self): pass\n def noise(self): pass\n'
    reduced, diag = reduce_class(text, {'methods': ['__init__']})
    assert '__new__' in reduced and 'noise' not in reduced


def test_large_class_keeps_last_method_and_target_is_masked_before_ranking(tmp_path):
    path = tmp_path / 'app.py'
    path.write_text('class Client:\n    padding = "' + 'x' * 17000 + '"\n    def fetch(self, value: HiddenGold):\n        return value\n')
    kb = build_project_kb(tmp_path)
    before = copy.deepcopy(kb)
    result = top_project_types(kb, 'value', 'value.fetch()', target_function='fetch', target_scope='arg', target_members={'methods': ['fetch']})
    text = result[0]['definition']
    assert 'HiddenGold' not in text and 'return value' in text
    assert 'padding' not in text
    assert kb == before


def test_variable_annotation_masked_in_class_and_callee_copies():
    text = 'class C:\n def f(self):\n  value: HiddenGold = 1\n  return value\n'
    assert 'HiddenGold' not in mask_definition(text, 'f', 'value', 'local')


def test_shared_class_kb_does_not_read_method_return_labels(tmp_path):
    results = []
    path = tmp_path / 'app.py'
    for annotation in ('HiddenGoldA', 'HiddenGoldB'):
        path.write_text('class Client:\n def fetch(self) -> ' + annotation + ':\n  return 1\n')
        kb = build_project_kb(tmp_path)
        assert annotation not in str(kb)
        results.append(kb)
    assert results[0] == results[1]


@pytest.mark.parametrize('call,fallback', [('helper(value, 1)', False), ('helper(*values)', True)])
def test_exporter_callee_binding_and_full_fallback(tmp_path, monkeypatch, call, fallback):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data').mkdir()
    path = tmp_path / 'app.py'
    path.write_text('def helper(item: str, count: int):\n unused = 72\n return item * count\ndef target(value: HiddenGold):\n unused_target = 42\n values = (value, 1)\n return ' + call + '\n')
    parsed, _ = scan_project(tmp_path)
    methods = Function_methods.from_parsed(tmp_path, parsed)
    kb = build_project_kb(tmp_path)
    result = export_one({'scope': 'arg', 'name': 'value', 'loc': 'target@4', 'gttype': 'HiddenGold'}, path, function_methods=methods, project_kb=kb)
    text = result['interprocedural_slice']
    assert 'HiddenGold' not in text
    assert 'unused_target' not in text
    assert 'unused = 72' not in text
    assert 'return item * count' not in text
    diagnostics = result['recommendation_diagnostics']['context_reduction']
    assert any(d.get('callee') == 'app.helper' and d['mode'] == 'signature_only' for d in diagnostics)


def test_exporter_unchanged_shared_kb_across_annotation_and_label_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data').mkdir()
    path = tmp_path / 'app.py'
    outputs = []
    kb = None
    for annotation in ('HiddenGoldA', 'HiddenGoldB'):
        path.write_text('class Client:\n def fetch(self): return 1\n def noise(self): return 2\ndef target(client: ' + annotation + '):\n unused = 99\n return client.fetch()\n')
        parsed, _ = scan_project(tmp_path)
        methods = Function_methods.from_parsed(tmp_path, parsed)
        if kb is None:
            kb = build_project_kb(tmp_path)
        before = copy.deepcopy(kb)
        row = {'scope': 'arg', 'name': 'client', 'loc': 'target@4', 'gttype': annotation}
        result = export_one(row, path, function_methods=methods, project_kb=kb)
        assert kb == before
        outputs.append((result['interprocedural_slice'], result['recommendation_types']))
    assert outputs[0] == outputs[1]
