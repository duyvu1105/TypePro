from copy import deepcopy
import json

import pytest

from test_graph_context import Tokenizer
from test_graph_dataset import repository, roster
from typepro.analysis.evidence_graph import TargetSpec
from typepro.analysis.graph_context import GraphContextProject
from typepro.data.graph_dataset import EVIDENCE_SCHEMA, export_graph_dataset, read_jsonl, sha256, verify_graph_dataset
from typepro.data.model_preprocess import prepare_row, preprocess_dataset, validate_model_dataset, validate_model_row
from typepro.shared.context_packing import prompt_token_ids, training_token_ids


class OtherTokenizer(Tokenizer):
    chat_template = 'a-different-model-template'

    def apply_chat_template(self, *args, **kwargs):
        return [987] * 50 + super().apply_chat_template(*args, **kwargs)


def test_raw_export_is_unpacked_and_shared_by_two_model_preprocessors(tmp_path):
    root, revision = repository(tmp_path)
    target = roster()
    source = tmp_path / 'shared'
    manifest = export_graph_dataset([target], {target['target_id']: 'int'}, root.parents[1],
                                    {'owner/repo': revision}, {'owner/repo': 'kb'}, output=source)
    assert manifest['schema_version'] == EVIDENCE_SCHEMA
    assert manifest['tokenizer_fingerprint'] is None
    assert manifest['input_length'] is manifest['label_length'] is None
    before = {p.name: sha256(p) for p in source.iterdir() if p.is_file()}
    row = next(read_jsonl(source / 'train.jsonl'))
    assert row['evidence'] and 'model_preprocess' not in row
    for number, tokenizer in enumerate((Tokenizer(), OtherTokenizer())):
        output = tmp_path / f'model{number}'
        prepared = preprocess_dataset(source, output, tokenizer, 20000, 64)
        result = next(read_jsonl(output / 'train.jsonl'))
        assert 'evidence' not in result
        prompt, sequence = training_token_ids(tokenizer, result['input'], result['label'], 20000, 64)
        assert sequence[:len(prompt)] == prompt
        assert prompt == prompt_token_ids(tokenizer, result['input'], 20000, 64)
        assert result['model_preprocess']['prompt_tokens'] == len(prompt)
        validate_model_dataset(output, tokenizer, 20000, 64)
        with pytest.raises(ValueError, match='differs'):
            validate_model_row(result, tokenizer, 19000, 64)
        assert prepared['source_manifest_sha256'] == sha256(source / 'manifest.json')
    assert json.loads((tmp_path / 'model0/manifest.json').read_text())['tokenizer_fingerprint'] != json.loads((tmp_path / 'model1/manifest.json').read_text())['tokenizer_fingerprint']
    assert before == {p.name: sha256(p) for p in source.iterdir() if p.is_file()}
    with pytest.raises(ValueError, match='before training'):
        validate_model_dataset(source, Tokenizer(), 20000, 64)


def test_budget_and_gold_labels_do_not_change_shared_graph_evidence():
    project = GraphContextProject('p', {'m.py': 'def f(x):\n return x\n'}, 'sha', 'kb')
    target = TargetSpec('p', 'm.py', 'f', 'return', 'f')
    packed = project.query(target, Tokenizer(), 100, 64)
    assert packed['outcome'] == 'budget_exceeded'
    raw = project.query(target)
    assert raw['outcome'] in {'ready', 'unresolved'}
    assert raw['evidence']
    assert raw['full_evidence'] == packed['full_evidence']
    assert raw['audit']['graph'] == packed['audit']['graph']
    raw.update(id='example', label='int', project='p', split='train')
    first = prepare_row(raw, Tokenizer(), 20000, 64)
    changed = deepcopy(raw)
    changed['label'] = 'str'
    second = prepare_row(changed, Tokenizer(), 20000, 64)
    assert first['input'] == second['input']
    assert first['model_preprocess'] == second['model_preprocess']
    assert prepare_row(raw, Tokenizer(), 100, 64)['outcome'] == 'budget_exceeded'
    with pytest.raises(ValueError, match='requires'):
        validate_model_row(raw, Tokenizer(), 20000, 64)


def test_neutral_dataset_merges_without_tokenizer_but_rejects_model_budget(tmp_path):
    from typepro.data.graph_dataset import merge_graph_datasets, write_json
    root, revision = repository(tmp_path)
    rows = [roster(), roster(name='x', scope='arg')]
    labels = {r['target_id']: 'int' for r in rows}
    inputs = []
    for i, row in enumerate(rows):
        path = tmp_path / str(i)
        export_graph_dataset([row], labels, root.parents[1], {'owner/repo': revision},
                             {'owner/repo': 'kb'}, output=path)
        inputs.append(path)
    merged = merge_graph_datasets(inputs, tmp_path / 'merged', rows)
    assert merged['schema_version'] == EVIDENCE_SCHEMA
    assert merged['total_targets'] == 2
    merged['input_length'] = 6144
    write_json(tmp_path / 'merged/manifest.json', merged)
    with pytest.raises(ValueError, match='cannot have'):
        verify_graph_dataset(tmp_path / 'merged')
