"""Regression cases for recursive evidence selection and signature-first callees."""
import ast
import sys
from pathlib import Path

import pytest

from typepro.analysis.ast_context_slicer import reduce_function
from typepro.analysis.export_slices import export_one
from typepro.analysis.function_methods import Function_methods
from typepro.analysis.project_index import scan_project


def sliced(source, parameters=(), **kwargs):
    original = ast.parse(source).body[0]
    before = ast.dump(original)
    reduction = reduce_function(original, parameters, **kwargs)
    assert ast.dump(original) == before
    code = ast.unparse(reduction.node)
    ast.parse(code)
    return code


def test_unrelated_blocks_removed_and_related_if_reduced():
    code = sliced('''def f(value):
 if debug:
  log_status()
 if enabled:
  noise = 123
  value.read()
 return value
''', ['value'])
    assert 'debug' not in code and 'noise' not in code
    assert 'if enabled:' in code and 'value.read()' in code


def test_nested_loop_keeps_input_and_break_condition_without_noise():
    code = sliced('''def f(value, items):
 for item in items:
  log(item)
  if item is None:
   break
  if enabled:
   noise = 12
   value.append(item)
 return value
''', ['value'])
    assert 'for item in items:' in code and 'break' in code
    assert 'if item is None:' in code and 'if enabled:' in code
    assert 'log(item)' not in code and 'noise' not in code


def test_while_keeps_control_updates_and_continue():
    code = sliced('''def f(value):
 i = 0
 while i < 10:
  i += 1
  if i == 3:
   continue
  value.append(i)
  noise = 99
 return value
''', ['value'])
    assert 'i += 1' in code and 'continue' in code and 'noise' not in code


def test_return_loop_retains_element_provenance_and_early_none():
    code = sliced('''def f(items):
 if items is None:
  return None
 result = []
 for item in items:
  converted = convert(item)
  result.append(converted)
  noise = 99
 return result
''', returns=True)
    assert 'return None' in code and 'convert(item)' in code
    assert 'result.append(converted)' in code and 'noise' not in code


def export(tmp_path, source, scope='arg'):
    path = tmp_path / 'app.py'
    path.write_text(source, encoding='utf-8')
    parsed, _ = scan_project(tmp_path)
    methods = Function_methods.from_parsed(tmp_path, parsed)
    target = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'target')
    return export_one({'scope': scope, 'name': 'value' if scope == 'arg' else 'target',
        'loc': f'target@{target.lineno}', 'gttype': 'HiddenGold'}, path,
        function_methods=methods, project_kb={'records': []})


@pytest.mark.parametrize('annotation,has_body', [('str', False), ('Any', True), ('object', True), ('', True)])
def test_callee_only_supplements_missing_or_broad_relevant_annotation(tmp_path, annotation, has_body):
    suffix = ': ' + annotation if annotation else ''
    result = export(tmp_path, f'''def helper(item{suffix}, debug: bool):
 noise = 123
 item.read()
def target(value: HiddenGold):
 helper(value, False)
 return value
''')
    code = result['interprocedural_slice']
    assert ('item.read()' in code) == has_body
    assert 'noise' not in code and 'HiddenGold' not in code


def test_unrelated_resolved_callee_not_expanded(tmp_path):
    result = export(tmp_path, '''def setup():
 setup_internals()
def helper(item):
 alias = item
 alias.read()
def target(value: HiddenGold):
 if enabled:
  setup()
  helper(value)
 return value
''')
    code = result['interprocedural_slice']
    assert 'def setup' not in code and 'setup_internals' not in code
    assert 'alias.read()' in code


def test_dynamic_callee_falls_back_to_signature_not_whole_body(tmp_path):
    result = export(tmp_path, '''def helper(item):
 exec(code)
 item.read()
def target(value: HiddenGold):
 helper(value)
 return value
''')
    assert 'def helper(item):' in result['interprocedural_slice']
    assert 'exec(code)' not in result['interprocedural_slice']


def test_return_annotation_controls_result_supplement(tmp_path):
    for annotation, body in [('Client', False), ('Any', True), ('', True)]:
        suffix = ' -> ' + annotation if annotation else ''
        result = export(tmp_path, f'''def make(){suffix}:
 noise = 123
 return Client()
def target() -> HiddenGold:
 return make()
''', scope='return')
        assert ('return Client()' in result['interprocedural_slice']) == body
        assert 'noise' not in result['interprocedural_slice']


def test_caller_nested_if_is_pruned_in_its_own_scope(tmp_path):
    result = export(tmp_path, '''def target(value: HiddenGold):
 return value
def main():
 if enabled:
  noise = 123
  client = Client()
  target(client)
  cleanup()
def other():
 client = Wrong()
''')
    code = result['interprocedural_slice']
    assert 'if enabled:' in code and 'client = Client()' in code
    assert 'noise' not in code and 'cleanup' not in code and 'Wrong' not in code


def test_caller_early_return_keeps_guard(tmp_path):
    result = export(tmp_path, '''def target(value: HiddenGold):
 return value
def main():
 if disabled:
  return
 client = Client()
 target(client)
''')
    assert 'if disabled:' in result['interprocedural_slice']


def test_callable_parameter_is_type_evidence():
    code = sliced('def f(value):\n value()\n noise = 12\n', ['value'])
    assert 'value()' in code and 'noise' not in code


def test_try_and_match_reduce_bodies_without_mutating_original():
    code = sliced('''def f(value):
 try:
  noise = 123
  value.read()
 except OSError:
  return None
 finally:
  value.close()
 match value:
  case Client() as client:
   client.fetch()
   other = 99
 return value
''', ['value'])
    assert 'noise' not in code and 'other' not in code
    assert 'except OSError:' in code and 'value.close()' in code
    assert 'client.fetch()' in code


def test_typevar_annotation_is_not_concrete(tmp_path):
    result = export(tmp_path, '''from typing import TypeVar
Payload = TypeVar('Payload')
def helper(item: Payload):
 item.read()
def target(value: HiddenGold):
 helper(value)
 return value
''')
    assert 'item.read()' in result['interprocedural_slice']


def test_plain_return_of_parameter_adds_no_discriminating_evidence(tmp_path):
    result = export(tmp_path, '''def helper(item):
 return item
def target(value: HiddenGold):
 helper(value)
 return value
''')
    assert 'return item' not in result['interprocedural_slice']


def test_pruned_finally_keeps_valid_try_skeleton():
    code = sliced('''def f(value):
 try:
  value.read()
 finally:
  cleanup()
''', ['value'])
    assert 'cleanup()' not in code and 'finally:' in code


def test_return_container_possible_mutations_are_retained():
    code = sliced('''def f(items):
 result = []
 alias = result
 for item in items:
  mutate(alias, item)
  log(item)
 return result
''', returns=True)
    assert 'mutate(alias, item)' in code and 'alias = result' in code
    assert 'log(item)' not in code


def test_return_element_factory_can_supply_missing_return_evidence(tmp_path):
    result = export(tmp_path, '''def make():
 return Client()
def target() -> HiddenGold:
 result = []
 result.append(make())
 return result
''', scope='return')
    assert 'return Client()' in result['interprocedural_slice']
