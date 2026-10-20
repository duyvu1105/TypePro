"""Symbol evidence is resolved from executable values, never target labels."""
import ast
import copy
import json
import sys

import pytest

from typepro.analysis.candidate_policy import POLICY, LEGACY_POLICY, source_evidence, score_candidate
from typepro.analysis.function_methods import Function_methods
from typepro.analysis.project_index import scan_project
from typepro.analysis.project_kb import top_project_types
from typepro.analysis.export_slices import export_one


def record(qualified):
    name = qualified.rsplit('.', 1)[-1]
    return dict(name=name, qualified_name=qualified, kind='class', source='third_party',
                definition=f'class {name}: pass')


def context(tmp_path, source):
    path = tmp_path / 'app.py'
    path.write_text(source)
    parsed, _ = scan_project(tmp_path)
    methods = Function_methods.from_parsed(tmp_path, parsed)
    function = next(n for n in ast.parse(source).body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 'target')
    return path, methods, function


@pytest.mark.parametrize('tail', ['return lib.Chart(data).mark_bar()',
                                  'chart = lib.Chart(data)\n    return chart.mark_bar()',
                                  'chart = lib.Chart(data)\n    other = chart\n    return other.mark_bar()'])
def test_return_expression_and_unambiguous_assignment_chain(tmp_path, tail):
    path, methods, fn = context(tmp_path, 'import external as lib\n'
                               f'def target(data) -> HiddenGold:\n    {tail}\n')
    records = [record('external.Chart'), record('external.tests.Chart')]
    before = copy.deepcopy(methods.context_catalog.trees)
    evidence = source_evidence(methods.context_catalog, path, fn, 'target', 'return', records)
    assert evidence == {'direct': set(), 'import': {'external.Chart'},
                        'symbol': {'external.Chart': 1.0}}
    assert {k: ast.dump(v) for k, v in before.items()} == {
        k: ast.dump(v) for k, v in methods.context_catalog.trees.items()}


def test_symbol_context_and_import_do_not_require_use_for_from_import(tmp_path):
    path, methods, fn = context(tmp_path, 'from external import Namespace as NS\n'
                               'from external import Chart\n'
                               'def target(data: NS) -> NS:\n'
                               '    """Namespace Chart"""\n'
                               '    chart = Chart(data)\n'
                               '    return len(data)\n')
    evidence = source_evidence(methods.context_catalog, path, fn, 'target', 'return',
                               [record('external.Namespace'), record('external.Chart')])
    assert evidence['import'] == {'external.Namespace', 'external.Chart'}
    assert evidence['symbol'] == {'external.Chart': .5}
    score, parts = score_candidate(record('external.Namespace'), '', 'zzz', '', {}, evidence)
    assert parts['symbol'] == 0 and parts['import'] == 1 and score == .5


@pytest.mark.parametrize('body', [
    '"""lib.Chart()"""\n    return 1',
    'x: lib.Chart\n    return 1',
    'def nested():\n        return lib.Chart()\n    return 1',
    'x = lambda: lib.Chart()\n    return 1',
    'x = [lib.Chart() for lib in values]\n    return 1',
])
def test_annotation_docstring_nested_and_comprehension_are_not_symbols(tmp_path, body):
    path, methods, fn = context(tmp_path, f'import external as lib\ndef target(values):\n    {body}\n')
    evidence = source_evidence(methods.context_catalog, path, fn, 'target', 'return', [record('external.Chart')])
    assert evidence['symbol'] == {} and evidence['import'] == set()


@pytest.mark.parametrize('body', [
    'chart = lib.Chart()\n    chart = other\n    return chart',
    'if flag:\n        chart = lib.Chart()\n    return chart',
    'return chart\n    chart = lib.Chart()',
])
def test_ambiguous_conditional_and_late_assignments_are_context_only(tmp_path, body):
    path, methods, fn = context(tmp_path, f'import external as lib\ndef target(flag):\n    {body}\n')
    evidence = source_evidence(methods.context_catalog, path, fn, 'target', 'return', [record('external.Chart')])
    assert evidence['symbol'] == {'external.Chart': .5}


def test_module_shadowing_blocks_symbol_and_import(tmp_path):
    path, methods, fn = context(tmp_path, 'import external as lib\ndef target(lib):\n    return lib.Chart()\n')
    assert source_evidence(methods.context_catalog, path, fn, 'target', 'return',
                           [record('external.Chart')]) == {'direct': set(), 'import': set(), 'symbol': {}}


@pytest.mark.parametrize('tail,expected', [
    ('self.value = value', {'external.Namespace'}),
    ('Namespace = other', set()),
    ('global Namespace\n    Namespace = other', set()),
    ('exec(code)', set()),
])
def test_unused_explicit_import_survives_receiver_stores_but_not_rebinding(tmp_path, tail, expected):
    path, methods, fn = context(tmp_path, 'from external import Namespace\n'
                               f'def target(self, value: Namespace):\n    {tail}\n')
    evidence = source_evidence(methods.context_catalog, path, fn, 'value', 'arg', [record('external.Namespace')])
    assert evidence['import'] == expected and evidence['symbol'] == {}


def test_caller_binding_awards_only_correct_argument(tmp_path):
    path, methods, fn = context(tmp_path, 'from external import Chart, Other\n'
                               'def target(value, unused): return value\n'
                               'chart = Chart()\ntarget(unused=Other(), value=chart)\n'
                               'def shadow(target): target(Other(), Chart())\n')
    evidence = source_evidence(methods.context_catalog, path, fn, 'value', 'arg',
                               [record('external.Chart'), record('external.Other')])
    assert evidence['symbol'] == {'external.Chart': 1.0}
    assert evidence['import'] == {'external.Chart', 'external.Other'}
    assert evidence['direct'] == {'external.Chart'}


def test_six_component_formula_and_no_repeated_reference_accumulation(tmp_path):
    item = record('external.Chart')
    evidence = {'direct': {'external.Chart'}, 'import': {'external.Chart'}, 'symbol': {'external.Chart': 1}}
    score, parts = score_candidate(dict(item, members=['plot']), item['definition'], 'Chart',
                                   'Chart Chart Chart', {'methods': ['plot', 'missing']}, evidence)
    assert score == pytest.approx(5 + 1.5 + 2 + 2 * parts['bm25'] + 1 + .5)
    assert 0 <= score <= 13.5
    old_score, old_parts = score_candidate(item, item['definition'], 'Chart', 'Chart', {}, evidence,
                                          policy=LEGACY_POLICY)
    assert 'symbol' not in old_parts
    assert old_score == pytest.approx(5 + 2 * old_parts['bm25'] + 1 + .5)


def test_export_masks_labels_and_sets_new_policy(tmp_path):
    results = []
    kb = {'records': [record('external.Chart'), record('external.tests.Noise')]}
    before = copy.deepcopy(kb)
    for gold in ('HiddenGoldA', 'HiddenGoldB'):
        source = f'import external as lib\ndef target(data) -> {gold}:\n    return lib.Chart(data).plot()\n'
        path, methods, fn = context(tmp_path, source)
        result = export_one({'scope': 'return', 'name': 'target', 'loc': 'target@2', 'gttype': gold},
                            path, function_methods=methods, project_kb=kb)
        assert result['candidate_policy_version'] == POLICY
        assert gold not in result['interprocedural_slice']
        chart = next(c for c in result['recommendation_types'] if c['name'] == 'Chart')
        assert chart['score_components']['symbol'] == 1
        assert chart['score_components']['direct'] == 0
        results.append(result['recommendation_types'])
    assert results[0] == results[1] and kb == before


def test_merge_rejects_mixed_candidate_policies_before_copying(tmp_path, monkeypatch):
    from typepro.data import merge
    builds = []
    for policy in (LEGACY_POLICY, POLICY):
        build = tmp_path / policy
        (build / 'metadata').mkdir(parents=True)
        (build / 'metadata/split_manifest.json').write_text('{}')
        (build / 'runtime_manifest.json').write_text(json.dumps({'candidate_policy_version': policy}))
        builds.append(str(build))
    output = tmp_path / 'merged'
    monkeypatch.setattr(sys, 'argv', ['merge', '--shard-build-dirs', *builds, '--work-dir', str(output)])
    with pytest.raises(ValueError, match='candidate policies differ'):
        merge.main()
    assert not output.exists()


def test_merge_checks_raw_policy_without_optional_schema_argument(tmp_path, monkeypatch):
    from typepro.data import merge
    build = tmp_path / 'build'
    (build / 'metadata').mkdir(parents=True)
    (build / 'metadata/split_manifest.json').write_text('{}')
    (build / 'runtime_manifest.json').write_text(json.dumps({'candidate_policy_version': POLICY}))
    (build / 'raw_slices').mkdir()
    (build / 'raw_slices/old.jsonl').write_text(json.dumps({'candidate_policy_version': LEGACY_POLICY}) + '\n')
    output = tmp_path / 'merged'
    monkeypatch.setattr(sys, 'argv', ['merge', '--shard-build-dirs', str(build), '--work-dir', str(output)])
    with pytest.raises(ValueError, match='policy differs from runtime'):
        merge.main()
    assert not output.exists()
