"""Pack shared graph evidence for one model before training or inference."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile

from typepro.analysis.evidence_graph import TargetSpec
from typepro.analysis.graph_render import render_groups
from typepro.analysis.graph_selection import EvidenceGroup
from typepro.data.graph_dataset import EVIDENCE_SCHEMA, read_jsonl, sha256, training_row, verify_graph_dataset, write_json
from typepro.shared.context_packing import pack_groups, tokenizer_fingerprint, training_token_ids

SCHEMA = 'typepro-model-preprocess-v1'


def validate_model_row(row, tokenizer, input_length, label_length, *, fingerprint=None):
    packing = row.get('model_preprocess')
    if 'evidence' in row and packing is None:
        raise ValueError('Shared graph evidence requires typepro.data.model_preprocess before training/inference')
    if packing is not None:
        expected = dict(tokenizer_fingerprint=fingerprint or tokenizer_fingerprint(tokenizer),
                        input_length=input_length, label_length=label_length)
        if any(packing.get(k) != v for k, v in expected.items()):
            raise ValueError('Prepared prompt tokenizer/template or token budget differs from this model run')


def validate_model_dataset(root, tokenizer, input_length, label_length):
    manifest_path = Path(root) / 'manifest.json'
    if not manifest_path.exists():
        return  # Existing baseline datasets remain supported.
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema_version') == EVIDENCE_SCHEMA:
        raise ValueError('Run python -m typepro.data.model_preprocess on shared graph evidence before training')
    if manifest.get('schema_version') == SCHEMA:
        validate_model_row(dict(model_preprocess=manifest), tokenizer, input_length, label_length)
        for name, expected in manifest['files'].items():
            path = Path(root) / name
            if not path.resolve().is_relative_to(Path(root).resolve()) or sha256(path) != expected:
                raise ValueError('Prepared model dataset hash mismatch: ' + name)


def prepare_row(row, tokenizer, input_length, label_length, *, fingerprint=None):
    # Labels are deliberately absent from selection and evidence rendering.
    target = TargetSpec(**row['target'])
    groups = [EvidenceGroup(**group) for group in row['evidence']]
    packed = pack_groups(tokenizer, groups, lambda gs: render_groups(target, gs), input_length, label_length)
    metadata = dict(tokenizer_fingerprint=fingerprint or tokenizer_fingerprint(tokenizer),
                    input_length=input_length, label_length=label_length,
                    retained_groups=packed.retained, omitted_groups=packed.omitted,
                    prompt_tokens=len(packed.prompt_ids), mandatory_tokens=packed.required_tokens)
    outcome = packed.outcome
    if outcome == 'ready':
        outcome = row['outcome']
        try:
            training_token_ids(tokenizer, packed.instruction, row['label'], input_length, label_length)
        except ValueError as error:
            if not str(error).startswith('Completion requires '):
                raise
            outcome = 'label_budget_exceeded'
    result = {k: v for k, v in row.items() if k not in {'input', 'evidence', 'budget_policy',
              'tokenizer_fingerprint', 'input_length', 'label_length'}}
    result.update(input=packed.instruction if outcome in {'ready', 'unresolved'} else None,
                  outcome=outcome, model_preprocess=metadata)
    return result


def preprocess_dataset(source, output, tokenizer, input_length=6144, label_length=64):
    source, output = Path(source), Path(output)
    raw = verify_graph_dataset(source)
    if raw['schema_version'] != EVIDENCE_SCHEMA:
        raise ValueError('Require model-neutral graph evidence, not a previously packed dataset')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Model preprocess output must be new/empty; preserve shared Dataset')
    output.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    fingerprint = tokenizer_fingerprint(tokenizer)
    with ExitStack() as stack:
        ledger = stack.enter_context((output / 'outcomes.jsonl').open('w', encoding='utf-8'))
        handles = {split: stack.enter_context((output / f'{split}.jsonl').open('w', encoding='utf-8'))
                   for split in ('train', 'validation', 'test')}
        for row in read_jsonl(source / 'outcomes.jsonl'):
            row = training_row(row)
            result = (prepare_row(row, tokenizer, input_length, label_length, fingerprint=fingerprint)
                      if row['outcome'] in {'ready', 'unresolved'} else row)
            line = json.dumps(result, ensure_ascii=False) + '\n'
            ledger.write(line)
            counts[result['outcome']] += 1
            if result['outcome'] in {'ready', 'unresolved'}:
                handles[row['split']].write(line)
    manifest = dict(schema_version=SCHEMA, source_manifest_sha256=sha256(source / 'manifest.json'),
                    tokenizer_fingerprint=fingerprint, total_targets=raw['total_targets'],
                    input_length=input_length, label_length=label_length, outcomes=dict(counts),
                    source_outcomes=raw['outcomes'],
                    files={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    write_json(output / 'manifest.json', manifest)
    validate_model_dataset(output, tokenizer, input_length, label_length)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--model-name', required=True)
    parser.add_argument('--revision')
    parser.add_argument('--chat-template-file', type=Path)
    parser.add_argument('--input-length', type=int, default=6144)
    parser.add_argument('--label-length', type=int, default=64)
    args = parser.parse_args()
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.model_name, **({'revision': args.revision} if args.revision else {}))
    if args.chat_template_file:
        tokenizer.chat_template = args.chat_template_file.read_text()
    # Fingerprint the reloadable artifact that train and inference will use.
    # Loading from a repository and from a saved directory can differ in
    # initialization metadata despite identical vocabulary/template bytes.
    with tempfile.TemporaryDirectory(prefix='typepro-model-tokenizer-') as temporary:
        tokenizer.save_pretrained(temporary)
        tokenizer = AutoTokenizer.from_pretrained(temporary, local_files_only=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        output = preprocess_dataset(args.data_dir, args.output_dir, tokenizer, args.input_length, args.label_length)
    tokenizer.save_pretrained(args.output_dir / 'tokenizer')
    output.update(tokenizer_source=args.model_name, tokenizer_revision=args.revision,
                  files={p.relative_to(args.output_dir).as_posix(): sha256(p)
                         for p in args.output_dir.rglob('*') if p.is_file() and p != args.output_dir / 'manifest.json'})
    write_json(args.output_dir / 'manifest.json', output)
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
