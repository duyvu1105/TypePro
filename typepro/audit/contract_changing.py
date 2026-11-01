"""Audit stored interventions by comparing ASTs, without executing sample code."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import copy
import json
from pathlib import Path

from typepro.shared.generative_chat import chat_token_ids
from typepro.training.contract_changing import POLICY, allows_none
from typepro.training.type_changing import sha256


def parse(code):
    return ast.parse(code.replace('<mask>', '__AUDIT_MASK__'))


def own_returns(f):
    def walk(n):
        for child in ast.iter_child_nodes(n):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            yield child
            yield from walk(child)
    return [n for n in walk(f) if isinstance(n, ast.Return)]


def compare_code(old_code, new_code, function, label, operation, *, unannotated_target=False):
    """Check that only declared wrappers, call adapters and target prose changed."""
    old, new = parse(old_code), parse(new_code)
    short = function.split('.')[-1]
    stats = Counter()

    def unwrap(n):
        if operation == 'wrap-list':
            assert isinstance(n, ast.List) and len(n.elts) == 1, 'Malformed return wrapper'
            return n.elts[0]
        assert isinstance(n, ast.Dict) and len(n.keys) == 1, 'Malformed dict wrapper'
        assert isinstance(n.keys[0], ast.Constant) and n.keys[0].value == 'value'
        return n.values[0]

    def target(n, path):
        return isinstance(n, ast.FunctionDef) and '.'.join((*path, n.name)) in {function,short} and (
            isinstance(n.returns, ast.Name) and n.returns.id == '__AUDIT_MASK__'
            or unannotated_target and n.returns is None)

    def equivalent(a, b, path=()):
        if isinstance(a, ast.Call) and isinstance(b, ast.Subscript) and isinstance(b.value, ast.Call):
            key = 0 if operation == 'wrap-list' else 'value'
            same_name = isinstance(a.func, ast.Name) and a.func.id == short or isinstance(a.func, ast.Attribute) and a.func.attr == short
            if same_name and isinstance(b.slice, ast.Constant) and b.slice.value == key:
                stats['call_adapters'] += 1
                return equivalent(a, b.value, path)
        if target(a,path):
            assert target(b,path), 'Masked target changed'
            a = copy.deepcopy(a)
            b = copy.deepcopy(b)
            if ast.get_docstring(a) is not None:
                a.body.pop(0)
                stats['removed_docstrings'] += 1
            if len(b.body) == len(a.body) + 1:
                assert allows_none(label) and isinstance(b.body[-1], ast.Return)
                end = unwrap(b.body.pop().value)
                assert isinstance(end, ast.Constant) and end.value is None
                stats['implicit_none_paths'] += 1
            assert len(a.body) == len(b.body), 'Unexpected target statement insertion/deletion'
            # Normalize only actual target returns, never nested helper returns.
            for ret in own_returns(b):
                ret.value = unwrap(ret.value)
                stats['return_wrappers'] += 1
            for ret in own_returns(a):
                if ret.value is None:
                    ret.value = ast.Constant(None)
            for key, value in ast.iter_fields(a):
                equivalent(value, getattr(b, key), (*path,a.name))
            return True
        if isinstance(a, ast.AST):
            assert type(a) is type(b), f'Unexpected AST change: {type(a).__name__} / {type(b).__name__}'
            next_path=(*path,a.name) if isinstance(a,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) else path
            for key, value in ast.iter_fields(a):
                equivalent(value, getattr(b, key), next_path)
        elif isinstance(a, list):
            assert isinstance(b, list) and len(a) == len(b), 'Unexpected statement/argument count change'
            for x, y in zip(a, b):
                equivalent(x, y, path)
        else:
            assert a == b, f'Unexpected scalar AST change: {a!r} / {b!r}'
        return True

    equivalent(old, new)
    return stats


def audit_dataset(source, data, tokenizer, label_length=64):
    source, data = Path(source), Path(data)
    audit = json.loads((data / 'type_intervention_audit.json').read_text())
    assert audit['policy'] == POLICY
    assert getattr(tokenizer,'name_or_path',None) == audit['tokenizer']
    counts = Counter()
    projects = Counter()
    labels = Counter()
    tokens = []
    completion_tokens=[]
    seen = set()
    parent_ids = set()
    reviews = []
    with (source / 'train.jsonl').open() as src, (data / 'train.jsonl').open() as dst:
        parent = None
        for line in dst:
            row = json.loads(line)
            assert row['id'] not in seen
            seen.add(row['id'])
            if 'type_intervention' not in row:
                assert line == next(src), 'Original rows changed or reordered'
                parent = row
                counts['original_rows'] += 1
                continue
            info = row['type_intervention']
            assert parent is not None and info['parent_id'] == parent['id']
            assert parent['id'] not in parent_ids, 'Repeated synthetic parent'
            parent_ids.add(parent['id'])
            op = info['operation']
            expected = f'List[{parent["label"]}]' if op == 'wrap-list' else f'Dict[str, {parent["label"]}]'
            from typepro.shared.type_labels import normalize_type_label
            assert row['label'] == normalize_type_label(expected)
            assert info['original_label'] == parent['label']
            for key in parent.keys() - {'id', 'input', 'label', 'interprocedural_slice', 'recommendation_types'}:
                assert row[key] == parent[key]
            stats = compare_code(parent['interprocedural_slice'], row['interprocedural_slice'],
                                 parent['target_function'], parent['label'], op)
            assert len(parent['recommendation_types']) == len(row['recommendation_types'])
            for a, b in zip(parent['recommendation_types'], row['recommendation_types']):
                assert {k:v for k,v in a.items() if k != 'definition'} == {k:v for k,v in b.items() if k != 'definition'}
                if a['definition'] != b['definition']:
                    from typepro.training.contract_changing import candidate_from_target_file
                    stats.update(compare_code(a['definition'], b['definition'], parent['target_function'], parent['label'], op,
                                              unannotated_target=candidate_from_target_file(parent,a)))
            from typepro.data.preprocess import format_input
            assert row['input'] == format_input(row['target_name'], row['target_function'], 'return',
                                                 row['interprocedural_slice'], row['recommendation_types'])
            prompt=chat_token_ids(tokenizer, row['input'])
            full=chat_token_ids(tokenizer, row['input'], row['label'])
            assert full[:len(prompt)]==prompt, 'Chat template response prefix changed'
            completion=len(full)-len(prompt)
            assert completion<=label_length, 'Synthetic annotation would be truncated'
            completion_tokens.append(completion)
            n = len(prompt)
            assert n <= audit['limits']['prompt_limit'] and n == info['prompt_tokens']
            tokens.append(n)
            counts.update(stats)
            counts['synthetic_rows'] += 1
            counts[op] += 1
            projects[row['project']] += 1
            labels[parent['label']] += 1
            if len(reviews) < 20 and projects[row['project']] == 1:
                reviews.append(dict(id=row['id'], project=row['project'], original_label=parent['label'],
                                    label=row['label'], operation=op, stats=dict(stats),
                                    original_code=parent['interprocedural_slice'], code=row['interprocedural_slice']))
        assert next(src, None) is None
    for split in ('train', 'validation', 'test'):
        assert sha256(source / f'{split}.jsonl') == audit['source_splits'][split]['sha256']
        assert sha256(data / f'{split}.jsonl') == audit['output_hashes'][split]
        if split != 'train':
            assert audit['source_splits'][split]['sha256'] == audit['output_hashes'][split]
    assert counts['original_rows'] == audit['counts']['original_rows']
    assert counts['synthetic_rows'] == audit['counts']['synthetic_rows']
    assert dict(projects) == audit['projects']
    assert dict(labels) == audit['source_label_counts']
    for measured, recorded in [('return_wrappers','returns'),('call_adapters','callers'),
                               ('removed_docstrings','docstrings'),('implicit_none_paths','implicit_none_paths')]:
        assert counts[measured] == audit['counts'].get('transformed:'+recorded,0)
    tokens.sort()
    result = dict(passed=True, counts=dict(counts), projects=len(projects), source_labels=len(labels),
                  output_hashes=audit['output_hashes'], tokenizer=getattr(tokenizer,'name_or_path',None),
                  verifier_code_sha256=sha256(Path(__file__)),
                  label_length=label_length, max_completion_tokens=max(completion_tokens),
                  synthetic_fraction=counts['synthetic_rows'] / (counts['original_rows'] + counts['synthetic_rows']),
                  token_quantiles={k: tokens[int((len(tokens)-1)*q)] for k,q in [('p50',.5),('p95',.95),('max',1)]},
                  readiness=audit['readiness'],
                  scope='AST transport, caller-adapter syntax, dataset integrity and actual tokenizer budget checked; source label truth and whole-project behavior not proven.')
    (data / 'contract_transport_verification.json').write_text(json.dumps(result, indent=2) + '\n')
    (data / 'review_samples.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in reviews))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--model-name', default='Qwen/Qwen2.5-Coder-0.5B-Instruct')
    parser.add_argument('--label-length',type=int,default=64)
    args = parser.parse_args()
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.model_name, local_files_only=True)
    print(json.dumps(audit_dataset(args.source, args.data_dir, tokenizer,args.label_length), indent=2))


if __name__ == '__main__':
    main()
