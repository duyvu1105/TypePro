"""Value barriers must reduce context without dropping unresolved type evidence."""
import ast

import pytest

from typepro.analysis.ast_context_slicer import FunctionCatalog, reduce_function
from typepro.analysis.type_evidence import TypeDependencies
from typepro.audit.regressions import replay


def run_case(tmp_path, source, *, scope='return', name='target', annotation='HiddenGold'):
    case = dict(id='type_stop', project='test/project', file='app.py', function='target',
                name=name, scope=scope, sources={'app.py': source}, required=[])
    result = replay(case, tmp_path, annotation)
    assert result['passed'], result['checks']
    return result


def test_scalar_result_stops_value_only_assignments_and_helper_expansion(tmp_path):
    result = run_case(tmp_path, '''def cleanup(raw):
    return raw.strip()
def target(raw) -> HiddenGold:
    cleaned = cleanup(raw)
    result = int(cleaned)
    return result
''')
    code = result['slice']
    assert 'result = int(cleaned)' in code and 'return result' in code
    assert 'cleaned = cleanup(raw)' not in code and 'def cleanup(' not in code
    assert any(d.get('component') == 'type_evidence' for d in result['diagnostics']['context_reduction'])


def test_closed_helper_signature_stops_only_its_input_value_chain(tmp_path):
    result = run_case(tmp_path, '''def cleanup(raw):
    return raw.strip()
def parse(value) -> int:
    return int(value)
def target(raw) -> HiddenGold:
    cleaned = cleanup(raw)
    result = parse(cleaned)
    return result
''')
    assert 'def parse(value) -> int:' in result['slice']
    assert 'def cleanup(' not in result['slice'] and 'cleaned = cleanup(raw)' not in result['slice']


@pytest.mark.parametrize('prefix,argument', [
    ('def int(x): return x\n', 'raw'),
    ('', 'raw, int'),
    ('from custom import int\n', 'raw'),
    ('from custom import *\n', 'raw'),
])
def test_shadowed_constructor_never_stops_dependencies(tmp_path, prefix, argument):
    result = run_case(tmp_path, prefix + f'''def cleanup(raw):
    return raw.strip()
def target({argument}) -> HiddenGold:
    cleaned = cleanup(raw)
    return int(cleaned)
''')
    assert 'cleaned = cleanup(raw)' in result['slice']
    assert 'def cleanup(' in result['slice']


@pytest.mark.parametrize('contract', ['Any', 'T', 'List[Any]', 'CustomAlias', 'Literal[3]'])
def test_open_contracts_preserve_input_provenance(tmp_path, contract):
    result = run_case(tmp_path, f'''from typing import Any, List, TypeVar, Literal
T = TypeVar('T')
CustomAlias = int
def cleanup(raw):
    return raw.strip()
def parse(value) -> {contract}:
    return value
def target(raw) -> HiddenGold:
    cleaned = cleanup(raw)
    return parse(cleaned)
''')
    assert 'cleaned = cleanup(raw)' in result['slice']


def test_argument_conversion_does_not_claim_the_input_is_int(tmp_path):
    result = run_case(tmp_path, '''def parse(value):
    return int(value)
def target(value: HiddenGold):
    return parse(value)
def caller(raw: str):
    value = raw.strip()
    target(value)
''', scope='arg', name='value')
    assert 'def parse(value):' in result['slice']
    assert 'value = raw.strip()' in result['slice'] and 'target(value)' in result['slice']


def test_mutable_contract_keeps_input_alias_and_mutation(tmp_path):
    result = run_case(tmp_path, '''def load():
    return []
def passthrough(items) -> list[int]:
    return items
def target() -> HiddenGold:
    items = load()
    result = passthrough(items)
    items.append('different')
    return result
''')
    assert 'items = load()' in result['slice']
    assert "items.append('different')" in result['slice']


def test_partial_container_keeps_item_contract_and_unresolved_branch(tmp_path):
    result = run_case(tmp_path, '''class Item: pass
def parse(row) -> Item:
    return Item()
def unknown(row):
    return row.value
def target(rows, flag) -> HiddenGold:
    output = []
    for row in rows:
        if flag:
            output.append(parse(row))
        else:
            output.append(unknown(row))
    return output
''')
    code = result['slice']
    assert 'def parse(row) -> Item:' in code and 'def unknown(row):' in code
    assert 'if flag:' in code and 'else:' in code and 'for row in rows:' in code
    assert 'output.append(parse(row))' in code and 'output.append(unknown(row))' in code


def test_branch_none_handler_and_finally_survive(tmp_path):
    result = run_case(tmp_path, '''def cleanup(raw):
    return raw.strip()
def target(raw, flag) -> HiddenGold:
    try:
        if flag:
            cleaned = cleanup(raw)
            return int(cleaned)
        return None
    except ValueError:
        return 'invalid'
    finally:
        release(raw)
''')
    code = result['slice']
    assert 'if flag:' in code and 'return None' in code and "return 'invalid'" in code
    assert 'except ValueError:' in code and 'finally:' in code


def test_stop_does_not_read_the_masked_target_annotation(tmp_path):
    source = '''def target(raw) -> HiddenGold:
    intermediate = raw.strip()
    return int(intermediate)
'''
    first = run_case(tmp_path / 'a', source, annotation='AliasA')
    second = run_case(tmp_path / 'b', source, annotation='DifferentAlias')
    assert first['slice'] == second['slice']
    assert [(c['name'], c['definition']) for c in first['candidates']] == [(c['name'], c['definition']) for c in second['candidates']]


def test_reducer_proof_does_not_mutate_shared_ast(tmp_path):
    source = 'def target(raw):\n    cleaned = raw.strip()\n    return int(cleaned)\n'
    path = tmp_path / 'app.py'; path.write_text(source)
    tree = ast.parse(source); fn = tree.body[0]; before = ast.dump(tree)
    catalog = FunctionCatalog([(path, 'app', source, tree)], tmp_path)
    proof = TypeDependencies(catalog, path, fn)
    reduced = reduce_function(fn, returns=True, type_dependencies=proof)
    assert ast.dump(tree) == before
    assert 'cleaned = raw.strip()' not in ast.unparse(reduced.node)


@pytest.mark.parametrize('helper', [
    "@wrapper\ndef parse(value) -> int:\n    return value\n",
    "async def parse(value) -> int:\n    return value\n",
    "def parse(value) -> int:\n    yield value\n",
])
def test_decorated_async_and_generator_contracts_do_not_stop(tmp_path, helper):
    result = run_case(tmp_path, helper + '''def cleanup(raw):
    return raw.strip()
def target(raw) -> HiddenGold:
    cleaned = cleanup(raw)
    return parse(cleaned)
''')
    assert 'cleaned = cleanup(raw)' in result['slice']


def test_scalar_branch_keeps_value_used_by_another_return(tmp_path):
    result = run_case(tmp_path, '''def cleanup(raw):
    return raw.strip()
def target(raw, flag) -> HiddenGold:
    cleaned = cleanup(raw)
    if flag:
        return int(cleaned)
    return cleaned
''')
    assert 'cleaned = cleanup(raw)' in result['slice']
    assert 'def cleanup(' in result['slice']


def test_finally_dependencies_are_not_cut_by_scalar_proof(tmp_path):
    result = run_case(tmp_path, '''def cleanup(raw):
    return raw.strip()
def target(raw) -> HiddenGold:
    cleaned = cleanup(raw)
    try:
        return int(cleaned)
    finally:
        release(cleaned)
''')
    assert 'cleaned = cleanup(raw)' in result['slice']
    assert 'release(cleaned)' in result['slice']
