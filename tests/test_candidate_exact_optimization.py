"""Differential checks against the frozen policy used by completed shards."""
import copy
import importlib.util
import json
import random
import sys
from pathlib import Path

import pytest

from typepro.analysis import candidate_policy as policy
from typepro.analysis.BM25 import bm25_similarity
from typepro.analysis.project_kb import top_project_types
from typepro.data.preprocess import format_input

REFERENCE_PATH = Path(__file__).parent / 'fixtures/candidate_weighted_v1_reference.py'
spec = importlib.util.spec_from_file_location('candidate_reference', REFERENCE_PATH)
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


@pytest.mark.parametrize('method', ['s_over_splusc', 'one_minus_exp', 'sigmoid', 'fallback'])
def test_bm25_matches_every_float_bit(method):
    rng = random.Random(20717)
    words = ['client', 'get', 'url', 'λ', 'request', 'response', '<mask>', 'value']
    pairs = [('', ''), ('', 'client'), ('client client get', 'get url client')]
    pairs += [(' '.join(rng.choices(words, k=rng.randrange(100))),
               ' '.join(rng.choices(words, k=rng.randrange(200)))) for _ in range(100)]
    pairs += [('client ' * 6000, 'request client ' * 4000)]  # bypass cache size cap
    for left, right in pairs:
        for options in ({}, {'return_raw': True}, {'k1': .8, 'b': .2, 'c': .3},
                        {'alpha': .07, 'sigmoid_a': .2, 'sigmoid_b': -1.0, 'normalize': False}):
            actual = bm25_similarity(left, right, method=method, **options)
            expected = reference.bm25_similarity(left, right, method=method, **options)
            assert actual.hex() == expected.hex()


def records(count):
    return [{'name': f'Client{i}', 'qualified_name': f'app.Client{i}', 'kind': 'class', 'source': 'project',
                 'members': ['get', 'close'] if i % 2 else [],
                 'definition': f'class Client{i}:\n    """Client λ {i}."""\n'
                 '    def get(self, url):\n        return url\n'
                 '    def close(self):\n        return None\n'} for i in range(count)]


@pytest.mark.parametrize('count', [0, 1, 10, 30, 300])
def test_entire_candidate_output_and_input_match_reference(count):
    kb = {'records': records(count)}
    if count:
        kb['records'] += [copy.deepcopy(kb['records'][0])]
        kb['records'][0]['definition'] += '    def unused(self):\n        return "' + 'x' * 9000 + '"\n'
    original = copy.deepcopy(kb)
    for target, code, scope, members in [
        ('client', 'def target(client: <mask>): return client.get(url)', 'arg', {'methods': ['get']}),
        ('zzz', '', 'arg', {}),
        ('fetch', 'def fetch() -> <mask>: return Client0()', 'return', {}),
    ]:
        kwargs = {'target_function': 'target' if scope == 'arg' else 'fetch', 'target_scope': scope,
                  'target_members': members,
                  'evidence': {'direct': {'app.Client0'}, 'import': {'app.Client1'}}}
        expected = reference.top_project_types(kb, target, code, **kwargs)
        for _ in range(2):  # cold and warm cache must both be exact
            actual = top_project_types(kb, target, code, **kwargs)
            assert actual == expected
            assert json.dumps(actual, ensure_ascii=False) == json.dumps(expected, ensure_ascii=False)
            def prompt(items, target=target, scope=scope, code=code):
                return format_input(target, 'target', scope, code, [
                    {'type': c['name'], 'qualified_name': c['qualified_name'], 'definition': c['definition']}
                    for c in items])
            assert prompt(actual) == prompt(expected)
    assert kb == original


@pytest.mark.parametrize('maximum', [0, 1, 80, 600, 1600, 4000])
def test_summary_and_character_distribution_match_reference(maximum):
    definitions = ['class Small: pass', 'class Broken:\n    def get(self):',
                   'class ' + 'X' * 700 + ': pass',
                   'class Large:\n' + ''.join(f'    def get_{i}(self): return {i}\n' for i in range(160)),
                   'def f(value: <mask>):\n    """λ doc."""\n    return "' + 'x' * 40000 + '"']
    for definition in definitions:
        assert policy.fit_definition(definition, maximum) == reference.fit_definition(definition, maximum)
    items = [dict(item, score=float(i + 1)) for i, item in enumerate(records(10))]
    for item in items:
        item['definition'] += '    def unused(self):\n        return "' + 'x' * 9000 + '"'
    assert policy.allocate_characters(items) == reference.allocate_characters(items)


def test_cache_keys_use_masked_content_and_never_share_mutable_results():
    a = 'class Client:\n    def target(self, value: <mask>): return value'
    b = 'class Client:\n    def target(self, value: bytes): return value'
    assert policy.fit_definition(a, 80) == reference.fit_definition(a, 80)
    assert policy.fit_definition(b, 80) == reference.fit_definition(b, 80)
    assert policy.structural_text(a) != policy.structural_text(b)
    first = policy.allocate_characters(records(2))
    first[0]['definition'] = 'modified'
    assert policy.allocate_characters(records(2)) == reference.allocate_characters(records(2))


@pytest.mark.parametrize('case_id', [
    'superset_collection', 'workshop_range', 'workshop_newtype', 'foolbox_tuple_alias',
    'subhub_symlink', 'mapping_constructor', 'adventofcode_lambda',
    'nicecream_wildcards', 'mort_documented_caller',
])
def test_exported_source_evidence_matches_reference(case_id, tmp_path, monkeypatch):
    from typepro.analysis import export_slices
    from typepro.audit.regressions import CASES, replay

    case = next(case for case in CASES if case['id'] == case_id)
    expected = replay(case, tmp_path / 'source')
    # Reuse the same source paths so definition metadata is comparable.
    with monkeypatch.context() as guard:
        guard.setattr(export_slices, 'top_project_types', reference.top_project_types)
        guard.setattr(policy, 'source_evidence', reference.source_evidence)
        baseline = replay(case, tmp_path / 'source')
    for field in ('slice', 'candidates', 'checks', 'passed'):
        assert expected[field] == baseline[field]


def test_old_and_optimized_shards_merge_with_identical_contract(tmp_path, monkeypatch):
    from typepro.data import merge

    schema = 'typepro-project-kb-top10-generative-v17-catalog-fallback-audit'
    inputs = []
    for name, function in [('completed', reference.top_project_types), ('optimized', top_project_types)]:
        build = tmp_path / name
        inputs.append(str(build))
        (build / 'metadata').mkdir(parents=True)
        (build / 'metadata/split_manifest.json').write_text('{"split_profile":"paper_project"}')
        runtime = {'retrieval_schema_version': schema, 'candidate_policy_version': policy.POLICY,
                   'context_policy_version': 'ast-context-v7-verified-signature-evidence',
                   'project_revision_lock_sha256': 'same-locked-project-revisions',
                   'revision_lock_source': {'version': 13}, 'revision_lock_policy': 'exact',
                   'code_revision': name}
        (build / 'runtime_manifest.json').write_text(json.dumps(runtime))
        (build / 'raw_slices').mkdir()
        candidates = function({'records': records(20)}, 'client', 'client.get(url)',
                              target_members={'methods': ['get']})
        row = {'recommendation_types': candidates, 'candidate_policy_version': policy.POLICY,
               'candidate_definition_max_chars': policy.DEFINITION_CHARS,
               'context_policy_version': runtime['context_policy_version'],
               'target_masking_version': 'typepro-shared-kb-masked-source-v7-resolved-bounded-context'}
        (build / f'raw_slices/{name}.jsonl').write_text(json.dumps(row) + '\n')
    assert (tmp_path / 'completed/raw_slices/completed.jsonl').read_bytes() == (
        tmp_path / 'optimized/raw_slices/optimized.jsonl').read_bytes()
    output = tmp_path / 'merged'
    monkeypatch.setattr(sys, 'argv', ['merge', '--shard-build-dirs', *inputs,
                                     '--work-dir', str(output), '--expected-retrieval-schema', schema])
    merge.main()
    assert len(list((output / 'raw_slices').glob('*.jsonl'))) == 2
