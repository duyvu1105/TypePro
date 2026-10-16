"""User regressions plus controls for scope, rebindings, aliases and imports."""
import ast
import sys
from pathlib import Path

import pytest

from typepro.audit.regressions import CASES, replay
from typepro.analysis.ast_context_slicer import FunctionCatalog, reduce_function
from typepro.analysis.project_kb import build_project_kb
from typepro.analysis.project_index import scan_project, project_module_aliases


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
def test_all_supplied_evidence_survives(case, tmp_path):
    result = replay(case, tmp_path)
    assert result['passed'], [c for c in result['checks'] if not c['passed']]
    if case['id'] == 'foolbox_tuple_alias':
        assert len(result['candidates']) == 10
        assert any(c['name'] == 'ModelAndData' for c in result['candidates'])
        assert 'ModelAndData' not in result['slice']  # similarity is not a proven dependency


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
def test_annotation_changes_cannot_change_retained_evidence(case, tmp_path):
    first = replay(case, tmp_path, 'HiddenGoldA')
    second = replay(case, tmp_path, 'CompletelyDifferentGold')
    assert first['passed'] and second['passed']
    assert first['slice'] == second['slice']
    assert [(c['name'], c['definition']) for c in first['candidates']] == [(c['name'], c['definition']) for c in second['candidates']]


def catalog(tmp_path, sources):
    for name, source in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
    parsed, _ = scan_project(tmp_path)
    return FunctionCatalog(parsed, tmp_path)


@pytest.mark.parametrize('tail', [
    'target = other\ntarget(7)',
    'if enabled:\n target = other\ntarget(7)',
    'target(7)\ndef target(x): return x',
    'class C:\n value = target(7)',
])
def test_module_calls_do_not_use_shadowed_late_or_class_bindings(tmp_path, tail):
    prefix = '' if tail.startswith('target(7)\ndef') else 'def target(x): return x\n'
    cat = catalog(tmp_path, {'app.py': prefix + tail + '\n'})
    assert not cat.callers('app.target')


def test_main_guard_and_module_argument_dependencies_survive(tmp_path):
    case = dict(id='guard', project='test', file='app.py', function='target', name='value', scope='arg',
                sources={'app.py': '''def target(value: HiddenGold): return value
if __name__ == '__main__':
    actual = range(1, 3)
    noise = 'drop_me'
    target(actual)
'''}, required=[('slice', "if __name__ == '__main__':"), ('slice', 'actual = range(1, 3)'), ('slice', 'target(actual)')])
    result = replay(case, tmp_path)
    assert result['passed']
    assert 'drop_me' not in result['slice']


@pytest.mark.parametrize('prefix,expected', [
    ('from facade import helper', True),
    ('from broken import helper', False),
    ('from cyclic import helper', False),
])
def test_explicit_reexports_preserve_scope_safety(tmp_path, prefix, expected):
    cat = catalog(tmp_path, {
        'app.py': prefix + '\ndef caller(value): return helper(value)\n',
        'origin.py': 'def helper(value: str) -> int: return 1\n',
        'facade.py': 'from origin import helper\n',
        'broken.py': 'from origin import helper\nhelper = replacement\n',
        'cyclic.py': 'from cycle2 import helper\n',
        'cycle2.py': 'from cyclic import helper\n',
    })
    caller = cat.trees[str((tmp_path / 'app.py').resolve())].body[-1]
    record, _ = cat.resolve(caller.body[0].value, tmp_path / 'app.py', caller)
    assert (record is not None) == expected
    if record:
        assert record[1] == 'origin.helper'


def test_lambda_shadowing_does_not_poison_sibling_call(tmp_path):
    cat = catalog(tmp_path, {'app.py': '''def helper(value: str): return value
def target(value):
    result = helper(value)
    ignored = lambda helper: helper(value)
    return result
'''})
    fn = cat.trees[str((tmp_path / 'app.py').resolve())].body[-1]
    assert cat.resolve(fn.body[0].value, tmp_path / 'app.py', fn)[0][1] == 'app.helper'
    assert cat.resolve(fn.body[1].value.body, tmp_path / 'app.py', fn)[0] is None


def test_returned_collection_tracks_aliases_nested_loops_and_rebinding():
    source = '''def f(db):
    rows = db.fetch()
    for row in rows:
        alias = row
        alias['kind'] = 'mapping'
        row = independent
        row['noise_after_rebinding'] = 'drop_me'
        noise = 'unrelated'
    for other in unrelated_rows:
        other['unrelated_mutation'] = 1
    return rows
'''
    fn = ast.parse(source).body[0]
    before = ast.dump(fn)
    code = ast.unparse(reduce_function(fn, returns=True).node)
    assert "alias['kind'] = 'mapping'" in code
    assert 'noise_after_rebinding' not in code and 'unrelated_mutation' not in code
    assert "noise = 'unrelated'" not in code
    assert ast.dump(fn) == before
    nested = ast.parse('''def f(db):
    groups = db.fetch()
    for group in groups:
        for row in group:
            row['kind'] = 'mapping'
    return groups
''').body[0]
    assert "row['kind'] = 'mapping'" in ast.unparse(reduce_function(nested, returns=True).node)


@pytest.mark.parametrize('declaration', [
    "from typing import NewType\nUserId = NewType('UserId', int)\nNewType = fake",
    "def NewType(*args): return 7\nUserId = NewType('UserId', int)",
    "Config = settings['runtime_value']",
    "from typing import Tuple\nModelAndData = Tuple[Model, Tensor, Tensor]\nModelAndData = runtime_value",
])
def test_runtime_values_and_shadowed_constructors_are_not_alias_candidates(tmp_path, declaration):
    cat = catalog(tmp_path, {'app.py': declaration + '\n'})
    parsed, _ = scan_project(tmp_path)
    kb = build_project_kb(tmp_path, parsed_files=parsed)
    assert not [r for r in kb['records'] if r['kind'] == 'type_alias']


def test_imported_alias_binding_is_preserved_but_local_shadow_is_not(tmp_path):
    cat = catalog(tmp_path, {'types.py': "from typing import NewType\nUserId = NewType('UserId', int)\n",
                             'app.py': 'from types import UserId\ndef caller(): return UserId(7)\ndef shadow(UserId): return UserId(8)\n'})
    tree = cat.trees[str((tmp_path / 'app.py').resolve())]
    values, diagnostics = cat.alias_context(tmp_path / 'app.py', tree.body[1], tree.body[1])
    assert any("NewType('UserId', int)" in v for v in values)
    assert diagnostics[0]['resolution'] == 'resolved'
    assert not cat.alias_context(tmp_path / 'app.py', tree.body[2], tree.body[2])[0]


def test_renamed_alias_import_keeps_the_binding_in_context(tmp_path):
    cat = catalog(tmp_path, {'types.py': "from typing import NewType\nUserId = NewType('UserId', int)\n",
                             'app.py': 'from types import UserId as U\ndef caller(): return U(7)\n'})
    fn = cat.trees[str((tmp_path / 'app.py').resolve())].body[-1]
    values, _ = cat.alias_context(tmp_path / 'app.py', fn, fn)
    assert 'from types import UserId as U' in values
    assert any("NewType('UserId', int)" in v for v in values)


def test_arbitrary_link_looking_text_is_not_a_module_alias(tmp_path):
    (tmp_path / 'shared').mkdir()
    (tmp_path / 'hub').mkdir()
    (tmp_path / 'hub/shared').write_text('../shared', encoding='utf-8')
    assert project_module_aliases(tmp_path) == {}


def test_unknown_element_mutation_keeps_call_without_guessing_body():
    fn = ast.parse('''def target(db):
    rows = db.fetch()
    for row in rows:
        mutate(row)
        row = independent
        mutate_rebound(row)
    return rows
''').body[0]
    code = ast.unparse(reduce_function(fn, returns=True).node)
    assert 'mutate(row)' in code
    assert 'mutate_rebound' not in code


def test_intermediate_reexport_dynamic_effect_is_rejected(tmp_path):
    cat = catalog(tmp_path, {'app.py': 'from facade import helper\ndef caller(x): return helper(x)\n',
                             'facade.py': 'from origin import helper\nexec(code)\n',
                             'origin.py': 'def helper(x: str): return x\n'})
    fn = cat.trees[str((tmp_path / 'app.py').resolve())].body[-1]
    assert cat.resolve(fn.body[0].value, tmp_path / 'app.py', fn)[0] is None


def test_caller_and_alias_provenance_is_required_before_publication(tmp_path):
    import json
    from typepro.audit.context import audit, POLICY, MASKING
    row = dict(context_policy_version=POLICY, target_masking_version=MASKING,
               candidate_definition_max_chars=8000, recommendation_types=[],
               recommendation_diagnostics={'context_reduction': [dict(component='alias', resolution='resolved')]})
    (tmp_path / 'raw.jsonl').write_text(json.dumps(row) + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='Unproven caller or alias'):
        audit(tmp_path)


def test_git_symlink_stub_cannot_map_outside_project(tmp_path):
    import subprocess
    root = tmp_path / 'repo'
    root.mkdir()
    (tmp_path / 'outside').mkdir()
    (root / 'linked').write_text('../outside', encoding='utf-8')
    subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
    digest = subprocess.run(['git', '-C', str(root), 'hash-object', '-w', '--stdin'],
                            input='../outside', text=True, capture_output=True, check=True).stdout.strip()
    subprocess.run(['git', '-C', str(root), 'update-index', '--add', '--cacheinfo',
                    f'120000,{digest},linked'], check=True, capture_output=True)
    assert project_module_aliases(root) == {}
