"""Whole masked-slice lexical evidence, version isolation, and bounded work."""
import copy
import random
import re
from pathlib import Path

import pytest

from typepro.analysis import candidate_policy as policy
from typepro.analysis.project_kb import top_project_types


def item(name='Chart', definition='class Chart: pass'):
    return dict(name=name, qualified_name='external.' + name, definition=definition,
                kind='class', source='third_party')


@pytest.mark.parametrize('code,visible', [
    ('from external import Chart', 1),
    ('def target():\n    """Return a Chart."""\n    return value', 1),
    ('return lib.Chart(data).plot()', 1),
    ('other: CHART', 1),
    ('Chart Chart Chart', 1),
    ('ChartBuilder Chart_1 myChart ChartChart', 0),
    ('', 0),
])
def test_name_visible_is_one_whole_token_anywhere_in_masked_slice(code, visible):
    _, parts = policy.score_candidate(item(), 'class Chart: pass', 'target', code, {}, {})
    assert parts['name_visible'] == visible
    assert parts['direct'] == parts['symbol'] == parts['import'] == 0


@pytest.mark.parametrize('code,definition', [
    ('alpha alpha beta', 'alpha beta beta gamma'),
    ('external Chart external', ''),
    ('class def return self', 'class Chart:\n    def get(self): return self'),
    (' '.join('token_' + str(i) for i in range(40)),
     ' '.join('token_' + str(i) for i in range(40))),
    ('', 'class Chart: pass'),
])
def test_overlap_matches_distinct_v20_tokens_and_caps_at_25(code, definition):
    record = item(definition=definition)
    tokens = lambda text: set(t.casefold() for t in re.findall(r'[A-Za-z_]\w*', text))
    expected = min(25, len(tokens(code) & tokens(
        record['name'] + ' ' + record['qualified_name'] + ' ' + definition))) / 25
    score, parts = policy.score_candidate(record, definition, 'target', code, {}, {})
    assert parts['lexical_overlap'] == expected
    assert score == sum(policy.WEIGHTS[k] * parts[k] for k in policy.WEIGHTS)


def test_old_symbol_policy_scores_are_unchanged_and_new_bonus_is_exact():
    rng = random.Random(317)
    vocabulary = ['Chart', 'external', 'class', 'def', 'value', 'λ', 'Kelvin', 'return']
    for _ in range(80):
        code = ' '.join(rng.choices(vocabulary, k=30))
        definition = ' '.join(rng.choices(vocabulary, k=45))
        evidence = {'direct': {'external.Chart'}, 'import': {'external.Chart'},
                    'symbol': {'external.Chart': .5}}
        before, old_parts = policy.score_candidate(
            item(), definition, 'target', code, {}, evidence, policy=policy.SYMBOL_POLICY)
        after, new_parts = policy.score_candidate(item(), definition, 'target', code, {}, evidence)
        assert old_parts == {k: new_parts[k] for k in old_parts}
        assert 'name_visible' not in old_parts and 'lexical_overlap' not in old_parts
        expected = sum(policy.SYMBOL_WEIGHTS[k] * old_parts[k] for k in policy.SYMBOL_WEIGHTS)
        assert before.hex() == expected.hex()
        assert after == pytest.approx(before + 2 * new_parts['name_visible'] + new_parts['lexical_overlap'])
        assert policy.lexical_text(code)[0] == policy.structural_text(code)
        context = policy.prepare_scoring_query('target', code, {})
        optimized, optimized_parts = policy.score_candidate(
            item(), definition, 'target', code, {}, evidence, query_context=context)
        assert optimized.hex() == after.hex() and optimized_parts == new_parts


def test_eight_component_formula_with_prepared_member_query():
    record = dict(item(), members=['plot', 'close'])
    code = 'return Chart().plot()'
    members = {'methods': ['plot', 'unknown']}
    evidence = {'direct': {'external.Chart'}, 'import': {'external.Chart'},
                'symbol': {'external.Chart': 1.0}}
    context = policy.prepare_scoring_query('Chart', code, members)
    score, parts = policy.score_candidate(record, record['definition'], 'Chart', code,
                                         members, evidence, query_context=context)
    assert parts['usage'] == .5
    assert score == pytest.approx(5 + 1.5 + 2 + 2 * parts['bm25'] + 1 + .5
                                 + 2 + parts['lexical_overlap'])
    assert 0 <= score <= 16.5


def test_query_is_prepared_once_and_kb_not_mutated(monkeypatch):
    records = [item('Class' + str(i), f'class Class{i}: pass') for i in range(40)]
    kb = {'records': records}
    original = copy.deepcopy(kb)
    code = 'from external import Class7\ndef target(): return Class7()'
    original_features = policy.lexical_text
    query_calls = []
    def features(text):
        if text == code:
            query_calls.append(text)
        return original_features(text)
    monkeypatch.setattr(policy, 'lexical_text', features)
    selected = top_project_types(kb, 'target', code)
    assert query_calls == [code]
    assert selected[0]['name'] == 'Class7'
    assert kb == original
    policy._cached_lexical_text.cache_clear()
    assert top_project_types(kb, 'target', code) == selected


def test_lexical_cache_is_bounded_and_keys_exact_masked_content():
    policy._cached_lexical_text.cache_clear()
    try:
        cache = policy._LexicalCache(maxsize=3, maxbytes=4096)
        for i in range(30):
            cache('class Value' + str(i))
        assert cache.cache_info().currsize <= 3
        assert cache.cache_info().retained_bytes <= 4096
        # A value larger than the entire budget is computed but not retained.
        before = cache.cache_info()
        assert cache('word ' * 10000) == policy._lexical_text('word ' * 10000)
        assert cache.cache_info().currsize == before.currsize
        assert cache.cache_info().retained_bytes == before.retained_bytes
        before = policy._cached_lexical_text.cache_info()
        policy.lexical_text('Chart ' * 7000)
        assert policy._cached_lexical_text.cache_info() == before
        assert policy.lexical_text('Chart')[1] == frozenset({'chart'})
        assert policy.lexical_text('Other')[1] == frozenset({'other'})
    finally:
        policy._cached_lexical_text.cache_clear()


def test_lexical_cache_evicts_by_memory_and_is_safe_for_parallel_readers():
    from concurrent.futures import ThreadPoolExecutor

    cache = policy._LexicalCache(maxsize=10000, maxbytes=4096)
    values = ['value_' + str(i) + ' ' + 'shared ' * 20 for i in range(80)] * 3
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(cache, values))
    assert results == [policy._lexical_text(text) for text in values]
    assert cache.cache_info().retained_bytes <= 4096
    assert cache.cache_info().currsize < 80
    cache.cache_clear()
    assert cache.cache_info().currsize == cache.cache_info().retained_bytes == 0


def test_v2_and_v3_are_distinct_supported_policies():
    assert policy.POLICY == 'candidate-lexical-v3'
    assert policy.SYMBOL_POLICY == 'candidate-symbol-v2'
    assert {policy.POLICY, policy.SYMBOL_POLICY, policy.LEGACY_POLICY} <= policy.SUPPORTED_POLICIES


def test_previous_v2_build_is_reprocessed_instead_of_reused(tmp_path, monkeypatch):
    import json
    import sys
    from typepro.data import prepare

    monkeypatch.setattr(sys, 'argv', ['prepare', '--no-build-import-kb', '--preview-samples', '0'])
    args = prepare.parse_args()
    previous = dict(retrieval_schema_version=args.retrieval_schema_version,
                    candidate_policy_version=policy.SYMBOL_POLICY,
                    context_policy_version='ast-context-v7-verified-signature-evidence')
    prepare.write_json(tmp_path / 'runtime_manifest.json', previous)
    prepare.write_json(tmp_path / 'project_status/owner__repository.json', previous)
    prepare.write_json(tmp_path / 'project_kb/owner__repository/knowledge_base.json', {'records': []})
    raw = tmp_path / 'raw_slices/owner__repository.jsonl'
    raw.parent.mkdir()
    raw.write_text('{"stale": true}\n')
    row = dict(file='repos/owner/repository/module.py', loc='global@global', name='value',
               scope='arg', cat='user-defined', gttype='Chart')
    monkeypatch.setattr(prepare, 'load_prepared_annotations', lambda _: [row])
    calls = []
    def clone(*args, **kwargs):
        calls.append(args[0])
        raise RuntimeError('stop before any network or export')
    monkeypatch.setattr(prepare, 'clone_project', clone)
    prepare.slice_projects(args, tmp_path, Path(__file__).resolve().parents[1])
    assert calls == ['owner/repository']
    assert not raw.exists()
    assert json.loads((tmp_path / 'runtime_manifest.json').read_text())['candidate_policy_version'] == policy.POLICY
