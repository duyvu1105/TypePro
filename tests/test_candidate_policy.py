"""Weighted selection, no-label evidence, and aggregate character limits."""
import ast
import copy

import pytest

from typepro.analysis.candidate_policy import (
    DEFINITION_CHARS,
    HEADER,
    MIN_SCORE,
    SUMMARY_CHARS,
    TOTAL_CHARS,
    allocate_characters,
    candidate_section,
    score_candidate,
    source_evidence as current_source_evidence,
    LEGACY_POLICY,
)
from typepro.analysis.function_methods import Function_methods
from typepro.analysis.export_slices import export_one
from typepro.analysis.project_index import scan_project
from typepro.analysis.project_kb import top_project_types
from typepro.data.preprocess import (
    format_input,
    normalized_recommendations,
    record_fields,
)



def source_evidence(*args, **kwargs):
    # Historical evidence fixtures remain differential checks for v1.
    return current_source_evidence(*args, policy=LEGACY_POLICY, **kwargs)

def candidate(name='Client', score=1, definition=None):
    return {'name': name, 'qualified_name': f'app.{name}', 'kind': 'class',
            'source': 'project', 'definition': definition or f'class {name}: pass', 'score': score}


def test_five_components_and_weights():
    item = dict(candidate(), members=['get', 'put'])
    text = 'class Client: pass'
    score, parts = score_candidate(item, text, 'Client', text,
                                  {'methods': ['get', 'missing']},
                                  {'direct': {'app.Client'}, 'import': {'app.Client'}},
                                  policy=LEGACY_POLICY)
    assert parts['direct'] == parts['import'] == parts['name'] == 1
    assert parts['usage'] == .5
    assert 0 <= parts['bm25'] <= 1
    assert score == pytest.approx(5 + 3 * .5 + 2 * parts['bm25'] + 1 + .5)
    assert 0 <= score <= 11.5


def test_threshold_inclusive_and_seed_does_not_bypass_it():
    kb = {'records': [candidate()]}
    assert top_project_types(kb, 'zzz', '', [{'name': 'Client'}]) == []
    # Name equality alone is exactly 1: threshold is inclusive.
    selected = top_project_types(kb, 'Client', '')
    assert len(selected) == 1 and selected[0]['score'] == MIN_SCORE
    assert selected[0]['score_components']['bm25'] == 0


def test_import_only_is_below_threshold():
    assert top_project_types({'records': [candidate()]}, 'zzz', '',
                             evidence={'import': {'app.Client'}}) == []
    assert normalized_recommendations({'recommendation_types': [candidate(score=.5)]}, 10) == []


def test_deterministic_ties_and_qualified_deduplication():
    records = [candidate(f'Kind{i}') for i in range(12)]
    evidence = {'direct': {r['qualified_name'] for r in records}}
    selected = top_project_types({'records': records + [records[0]]}, 'zzz', '', evidence=evidence)
    reverse = top_project_types({'records': list(reversed(records))}, 'zzz', '', evidence=evidence)
    assert len(selected) == 10
    assert [c['qualified_name'] for c in selected] == [c['qualified_name'] for c in reverse]


def test_total_budget_ten_large_candidates_unicode_and_weighted_allocation():
    definition = lambda name: f'class {name}:\n' + ''.join(
        f'    def method_{i}(self, value):\n        """Mô tả {i}."""\n        return value\n'
        for i in range(100))
    items = [candidate(f'Client{i}', score=10-i, definition=definition(f'Client{i}')) for i in range(10)]
    before = copy.deepcopy(items)
    result = allocate_characters(items)
    assert items == before and len(result) == 10
    assert len(candidate_section(result)) <= TOTAL_CHARS
    assert all(len(c['definition']) <= DEFINITION_CHARS for c in result)
    assert all(c['character_budget']['summary_chars'] <= SUMMARY_CHARS for c in result)
    assert result[0]['character_budget']['definition_budget'] > result[-1]['character_budget']['definition_budget']
    for c in result:
        ast.parse(c['definition'])
    normalized = normalized_recommendations({'recommendation_types': result}, 10)
    rendered = format_input('x', 'f', 'arg', 'def f(x): pass', normalized)
    assert len(rendered.split(HEADER, 1)[1]) + len(HEADER) <= TOTAL_CHARS
    assert '[QUALIFIED_NAME] app.Client0' in rendered


def test_unused_budget_goes_to_remaining_long_candidate():
    large = candidate('Large', 1, 'class Large:\n' + ''.join(
        f'    def method_{i}(self): return {i}\n' for i in range(150)))
    result = allocate_characters([candidate(score=10), large])
    alone = allocate_characters([large])
    assert result[1]['definition'] == alone[0]['definition']
    assert len(candidate_section(result)) <= TOTAL_CHARS


def test_impossible_header_is_dropped_without_cutting_identity():
    item = candidate('X' * 700)
    assert allocate_characters([item]) == []


def test_empty_candidates_preserve_sample():
    fields = record_fields({'name': 'value', 'gttype': 'str',
                            'interprocedural_slice': 'def f(value): pass', 'recommendation_types': []})
    assert all(fields[:3]) and fields[3] == []
    assert format_input('value', 'f', 'arg', 'pass', []).endswith(HEADER)


@pytest.mark.parametrize('annotation', ['HiddenGoldA', 'HiddenGoldB'])
def test_direct_evidence_uses_verified_calls_and_constructor_binding(tmp_path, annotation):
    source = f'''from external import Client as C
class Local: pass
def fetch(value: {annotation}): return value
fetch(C())
fetch(value=Local())
def shadowed(fetch):
    fetch(C())
'''
    path = tmp_path / 'app.py'
    path.write_text(source, encoding='utf-8')
    parsed, _ = scan_project(tmp_path)
    catalog = Function_methods.from_parsed(tmp_path, parsed).context_catalog
    function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef))
    records = [candidate('Local'), dict(candidate(), qualified_name='external.Client')]
    result = source_evidence(catalog, path, function, 'value', 'arg', records)
    assert result == {'direct': {'external.Client', 'app.Local'}, 'import': {'external.Client'}}
    # Shadowing the constructor parameter must not resolve to the import.
    shadow = ast.parse('def shadow(C):\n    return C()').body[0]
    assert source_evidence(catalog, path, shadow, 'shadow', 'return', records)['direct'] == set()


def test_rebinding_and_wrong_module_do_not_get_direct_points(tmp_path):
    path = tmp_path / 'app.py'
    path.write_text('from wrong import Client\nClient = factory\n'
                    'def fetch(value): return value\nfetch(Client())\n', encoding='utf-8')
    parsed, _ = scan_project(tmp_path)
    catalog = Function_methods.from_parsed(tmp_path, parsed).context_catalog
    function = next(n for n in catalog.trees[str(path.resolve())].body if isinstance(n, ast.FunctionDef))
    records = [dict(candidate(), qualified_name='external.Client')]
    result = source_evidence(catalog, path, function, 'value', 'arg', records)
    assert result == {'direct': set(), 'import': set()}


@pytest.mark.parametrize('qualified', [
    'numpy.typing.tests.data.pass.ufunc_config.func1',
    'cv2.config-3.PYTHON_EXTENSIONS_PATHS',
])
def test_invalid_import_expression_preserves_evidence_and_export(tmp_path, qualified):
    module = qualified.split('.')[0]
    records = [dict(candidate(), qualified_name=f'{module}.Client'),
               dict(candidate(), qualified_name=qualified)]
    expected = {'direct': {f'{module}.Client'}, 'import': {f'{module}.Client'}}
    results = []
    for gold in ('HiddenGoldA', 'HiddenGoldB'):
        source = (f'import {module} as lib\n'
                  f'def fetch(Client: {gold}): return Client\n'
                  'fetch(lib.Client())\n')
        path = tmp_path / 'app.py'
        path.write_text(source, encoding='utf-8')
        parsed, _ = scan_project(tmp_path)
        methods = Function_methods.from_parsed(tmp_path, parsed)
        function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef))
        kb = {'records': copy.deepcopy(records)}
        before = copy.deepcopy(kb)
        evidence = source_evidence(methods.context_catalog, path, function, 'Client', 'arg', kb['records'])
        assert evidence == expected
        # An invalid import spelling does not remove the record from other scores.
        selected = top_project_types(kb, 'Client', '', evidence=evidence)
        invalid = next(c for c in selected if c['qualified_name'] == qualified)
        assert invalid['score_components']['name'] == 1
        assert invalid['score_components']['import'] == 0
        result = export_one({'scope': 'arg', 'name': 'Client', 'loc': 'fetch@2',
                             'gttype': gold}, path, function_methods=methods, project_kb=kb)
        assert result is not None
        assert '<mask>' in result['interprocedural_slice']
        assert gold not in result['interprocedural_slice']
        assert kb == before
        results.append(result['recommendation_types'])
    assert results[0] == results[1]


def test_preprocess_and_verify_allow_empty_candidates(tmp_path, monkeypatch):
    import hashlib
    import json
    import sys

    from typepro.data import preprocess, verify

    raw = tmp_path / 'raw.jsonl'
    raw.write_text(json.dumps({'id': 'empty', 'url': 'https://github.com/owner/repo',
                              'split': 'train', 'name': 'value', 'scope': 'arg', 'gttype': 'str',
                              'interprocedural_slice': 'def f(value: <mask>): return value',
                              'recommendation_types': []}) + '\n', encoding='utf-8')
    output = tmp_path / 'dataset'
    monkeypatch.setattr(sys, 'argv', ['preprocess', '--input', str(raw), '--output-dir', str(output)])
    preprocess.main()
    row = json.loads((output / 'train.jsonl').read_text(encoding='utf-8'))
    assert row['recommendation_types'] == [] and row['label'] == 'str'
    assert row['candidate_policy_version'] is None  # Unknown raw provenance must stay unknown.
    manifest = {'schema_version': 'typepro-codet5p-generative-project-kb-v2', 'output': {}}
    for split in ('train', 'validation', 'test'):
        path = output / f'{split}.jsonl'
        manifest['output'][split] = {'file': path.name, 'rows': int(split == 'train'),
                                     'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    (output / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['verify', '--data-dir', str(output)])
    verify.main()
