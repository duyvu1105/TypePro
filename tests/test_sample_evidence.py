import copy
import json
import subprocess
import sys

import pytest

from typepro.analysis.evidence_bundle import block, build_bundle, validate_bundle, RETRIEVAL_SCHEMA
from typepro.analysis.project_kb import top_project_types
from typepro.shared.context_packing import ContextPacker, ContextBudgetError, pack_context
from typepro.shared.generative_chat import chat_token_ids


class Tokenizer:
    chat_template = 'test-template-v1'
    special_tokens_map = {}
    init_kwargs = {}

    def __init__(self, factor=1):
        self.factor = factor
        self.calls = 0

    def get_vocab(self):
        return {'factor': self.factor}

    def apply_chat_template(self, messages, tokenize, add_generation_prompt, return_dict=False):
        assert return_dict is False
        self.calls += 1
        text = ''.join(m['content'] + '\n' for m in messages)
        # Response retains the exact generation prefix, like the Qwen template.
        if add_generation_prompt:
            text += 'assistant:'
        else:
            text = ''.join(m['content'] + '\n' for m in messages[:-1]) + 'assistant:' + messages[-1]['content'] + '<end>'
        return [ord(c) for c in text for _ in range(self.factor)]


def sample():
    root = block('core', 'def target(x: <mask>):\n    return x.fetch()', required=True, priority=100)
    caller = block('caller', 'target(Client())', priority=80,
                   source={'file': 'app.py', 'line': 9, 'resolution': 'resolved'})
    candidate = block('candidate', '[TYPE] Client\n[DEFINITION]\nclass Client:\n' + '    field = 1\n' * 100,
                      summary='[TYPE] Client\n[QUALIFIED_NAME] app.Client', priority=70)
    caller['depends_on'] = [root['id']]
    candidate['depends_on'] = [root['id']]
    return {'id': 'one', 'target_name': 'x', 'target_function': 'target', 'target_scope': 'arg',
            'evidence_bundle': {'schema': 'typepro-evidence-v1', 'blocks': [root, caller, candidate]},
            'input': 'compatibility prompt', 'label': 'Client'}


def test_budget_uses_entire_model_template_and_never_cuts_core():
    row = sample()
    tokenizer = Tokenizer()
    packed = pack_context(row, tokenizer, 600)
    assert len(packed.token_ids) <= 600
    assert packed.token_ids == chat_token_ids(tokenizer, packed.instruction)
    assert row['evidence_bundle']['blocks'][0]['text'] in packed.instruction
    assert 'target(Client())' in packed.instruction
    assert packed.audit['summary_only']
    assert packed.instruction.endswith('[QUALIFIED_NAME] app.Client')


def test_two_tokenizers_choose_different_detail_from_same_dataset():
    row = sample()
    before = copy.deepcopy(row)
    full = pack_context(row, Tokenizer(), 2000)
    smaller = pack_context(row, Tokenizer(3), 2000)
    assert full.audit['summary_only'] == []
    assert smaller.audit['summary_only']
    assert row == before


def test_mandatory_overflow_fails_with_sample_identity():
    with pytest.raises(ContextBudgetError, match='Sample one: mandatory evidence'):
        pack_context(sample(), Tokenizer(), 10)


def test_pack_is_label_independent_and_cache_is_tokenizer_specific(tmp_path):
    row = sample()
    t = Tokenizer()
    packer = ContextPacker(t, 600, tmp_path)
    first = packer.pack(row)
    calls = t.calls
    row['label'] = 'SecretGold'
    assert packer.pack(row) == first
    assert t.calls == calls
    other = ContextPacker(Tokenizer(2), 600, tmp_path)
    assert packer.fingerprint != other.fingerprint
    assert len(list(tmp_path.glob('*.sqlite3'))) == 2
    packer.close()
    other.close()


@pytest.mark.parametrize('change', ['missing', 'cycle', 'duplicate', 'root', 'schema'])
def test_invalid_bundles_fail_closed(change):
    bundle = sample()['evidence_bundle']
    if change == 'missing':
        bundle['blocks'][1]['depends_on'] = ['missing']
    elif change == 'cycle':
        bundle['blocks'][0]['depends_on'] = [bundle['blocks'][1]['id']]
    elif change == 'duplicate':
        bundle['blocks'].append(copy.deepcopy(bundle['blocks'][0]))
    elif change == 'root':
        bundle['blocks'][0]['required'] = False
    else:
        bundle['schema'] = 'old'
    with pytest.raises(ValueError):
        validate_bundle(bundle)


def test_dependency_closure_is_kept_or_omitted_atomically():
    row = sample()
    root, caller, candidate = row['evidence_bundle']['blocks']
    caller['text'] = 'large caller ' * 500
    candidate['depends_on'].append(caller['id'])
    packed = pack_context(row, Tokenizer(), 600)
    assert set(packed.audit['kept']) == {root['id']}
    assert caller['id'] in packed.audit['omitted']
    assert candidate['id'] in packed.audit['omitted']


def test_build_retains_control_flow_and_separates_exact_caller_only():
    core = 'def target(x: <mask>):\n    if x:\n        return User()\n    return None'
    caller = 'def caller():\n    return target(User())'
    bundle = build_bundle(core + '\n' + caller,
                          [{'text': caller, 'source': {'file': 'app.py', 'line': 6}}], [], {})
    assert bundle['blocks'][0]['text'] == core
    assert bundle['blocks'][1]['text'] == caller
    assert bundle['blocks'][1]['depends_on'] == [bundle['blocks'][0]['id']]


def test_selected_candidate_evidence_precedes_character_truncation():
    definition = 'class Client:\n    def fetch(self):\n' + ''.join(
        f'        a{i} = {i}\n' for i in range(600)) + '        return User()'
    kb = {'records': [dict(name='Client', qualified_name='app.Client', kind='class',
                           source='project', definition=definition)]}
    before = copy.deepcopy(kb)
    evidence = []
    ranked = top_project_types(kb, 'client', 'client.fetch()', evidence_sink=evidence,
                               target_members={'methods': ['fetch']})
    assert ranked and len(ranked[0]['definition']) <= 4000
    assert 'return User()' in evidence[0]['definition']
    assert len(evidence[0]['definition']) > 4000
    assert kb == before
    bundle = build_bundle('def target(x: <mask>):\n    return x.fetch()', [], evidence, {})
    candidate = bundle['blocks'][1]
    assert 'return User()' in candidate['compact']
    assert 'a599' not in candidate['compact']
    row = dict(target_name='x', target_function='target', target_scope='arg', evidence_bundle=bundle)
    packed = pack_context(row, Tokenizer(), 900)
    assert packed.audit['compact_only'] == [candidate['id']]
    assert 'return User()' in packed.instruction


def test_export_and_preprocess_keep_masked_self_contained_evidence(tmp_path):
    from typepro.analysis.export_slices import export_one
    from typepro.analysis.function_methods import Function_methods
    from typepro.analysis.ast_context_slicer import FunctionCatalog
    import ast
    path = tmp_path / 'app.py'
    source = 'def target(x: SecretGold):\n    return x + 1\n\ndef caller():\n    return target(7)\n'
    path.write_text(source, encoding='utf-8')
    methods = Function_methods.empty()
    methods.context_catalog = FunctionCatalog([(path, '', source, ast.parse(source))])
    row = {'name': 'x', 'scope': 'arg', 'loc': 'target@1', 'gttype': 'int', 'url': 'https://example/owner/repo'}
    result = export_one(row, path, function_methods=methods, project_kb={'records': []})
    bundle = validate_bundle(result['evidence_bundle'])
    assert 'SecretGold' not in json.dumps(bundle)
    assert any(b['kind'] == 'caller' for b in bundle['blocks'])
    path.write_text(source.replace('SecretGold', 'OtherGold'), encoding='utf-8')
    second = export_one(row, path, function_methods=methods, project_kb={'records': []})
    assert second['evidence_bundle'] == bundle
    raw = tmp_path / 'raw.jsonl'
    raw.write_text(json.dumps(result) + '\n', encoding='utf-8')
    output = tmp_path / 'data'
    subprocess.run([sys.executable, '-m', 'typepro.data.preprocess', '--input', str(raw),
                    '--output-dir', str(output), '--require-evidence'], check=True, capture_output=True)
    rows = [json.loads(line) for p in output.glob('*.jsonl') for line in p.read_text().splitlines()]
    assert rows[0]['evidence_bundle'] == bundle
    packed = pack_context(rows[0], Tokenizer(), 1000)
    assert 'SecretGold' not in packed.instruction
    assert 'return x + 1' in packed.instruction


def test_frozen_v17_kb_can_feed_v18_without_reusing_rows(tmp_path):
    from typepro.data.kb_reuse import reuse_project_kb
    from test_kb_reuse import frozen, COMMIT
    source = tmp_path / 'old'
    frozen(source)
    reused = reuse_project_kb(source, 'owner/repo', COMMIT, tmp_path / 'new', RETRIEVAL_SCHEMA)
    assert reused
    assert not (tmp_path / 'new' / 'raw_slices').exists()


def test_training_length_and_collator_use_identical_packed_prompt():
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    from typepro.shared.generative_chat import left_pad_causal_batch
    path = Path(__file__).resolve().parents[1] / 'typepro/training/generative.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    length = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'training_sequence_length')
    train = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'train')
    collate = next(n for n in train.body if isinstance(n, ast.FunctionDef) and n.name == 'collate')
    tokenizer = Tokenizer()
    tokenizer.pad_token_id = 0
    scope = dict(ContextPacker=ContextPacker, chat_token_ids=chat_token_ids,
                 left_pad_causal_batch=left_pad_causal_batch, tokenizer=tokenizer,
                 args=SimpleNamespace(input_length=664, label_length=64),
                 packer=ContextPacker(tokenizer, 600))
    exec(compile(ast.Module(body=[length, collate], type_ignores=[]), str(path), 'exec'), scope)
    row = sample()
    batch = scope['collate']([row])
    measured = scope['training_sequence_length'](row, tokenizer, 664, 64, scope['packer'])
    packed = scope['packer'].pack(row)
    assert measured == int(batch['attention_mask'].sum())
    assert batch['input_ids'][0][:len(packed.token_ids)].tolist() == packed.token_ids
    assert batch['labels'][0][:len(packed.token_ids)].tolist() == [-100] * len(packed.token_ids)


def test_v18_merge_rejects_missing_evidence_before_copying(tmp_path, monkeypatch):
    from typepro.data import merge
    build = tmp_path / 'build'
    (build / 'metadata').mkdir(parents=True)
    (build / 'metadata/split_manifest.json').write_text('{}')
    (build / 'runtime_manifest.json').write_text(json.dumps(dict(
        retrieval_schema_version=RETRIEVAL_SCHEMA, candidate_policy_version='candidate-lexical-v3')))
    (build / 'raw_slices').mkdir()
    (build / 'raw_slices/rows.jsonl').write_text(json.dumps(dict(candidate_policy_version='candidate-lexical-v3')))
    monkeypatch.setattr(sys, 'argv', ['merge', '--shard-build-dirs', str(build), '--work-dir', str(tmp_path / 'merged')])
    with pytest.raises(ValueError, match='Unsupported evidence schema'):
        merge.main()
    assert not (tmp_path / 'merged').exists()
