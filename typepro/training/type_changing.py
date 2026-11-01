"""Conservative, train-only AST interventions with independently checked labels.

This is an isolated-program augmentation, not a semantics-preserving refactor.
Unsupported or ambiguous samples stay original. Never execute dataset code.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
import re
import shutil

from typepro.data.preprocess import format_input
from typepro.shared.type_labels import normalize_type_label

POLICY = 'type-changing-v1'
MASK = 'TPMSK0'  # Same byte length as <mask>, preserving AST source positions.
SCALARS = {'str', 'int', 'float', 'bool', 'bytes', 'complex'}
OPERATIONS = ('wrap-list', 'wrap-dict', 'element-float', 'instance-class')


class Unsupported(ValueError):
    pass


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def parse(code):
    if MASK in code:
        raise Unsupported('sentinel_collision')
    try:
        return ast.parse(code.replace('<mask>', MASK))
    except (SyntaxError, ValueError, RecursionError) as e:
        raise Unsupported('unparseable_code') from e


def canonical(label):
    node = ast.parse(normalize_type_label(label), mode='eval')
    class Normalize(ast.NodeTransformer):
        def visit_Name(self, n):
            n.id = {'List': 'list', 'Dict': 'dict', 'Type': 'type'}.get(n.id, n.id)
            return n
        def visit_Attribute(self, n):
            if isinstance(n.value, ast.Name) and n.value.id == 'typing':
                return self.visit(ast.Name(id=n.attr, ctx=ast.Load()))
            return self.generic_visit(n)
    return ast.dump(Normalize().visit(node), include_attributes=False)


def prepare(code, target):
    tree = parse(code)
    fs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
          and n.name == target]
    if len(fs) != 1:
        raise Unsupported('ambiguous_target_definition')
    f = fs[0]
    if not isinstance(f.returns, ast.Name) or f.returns.id != MASK:
        raise Unsupported('target_return_not_masked')
    if isinstance(f, ast.AsyncFunctionDef) or f.decorator_list or target.startswith('__'):
        raise Unsupported('special_or_decorated_function')
    if not f.body or not isinstance(f.body[-1], ast.Return):
        raise Unsupported('possible_implicit_return')
    nodes = list(ast.walk(f))
    forbidden = (ast.Yield, ast.YieldFrom, ast.Await, ast.Lambda, ast.Try,
                 ast.With, ast.AsyncWith, ast.Global, ast.Nonlocal)
    if any(isinstance(n, forbidden) or
           n is not f and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
           for n in nodes):
        raise Unsupported('unsupported_control_or_scope')
    if any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id == target
           for n in ast.walk(tree)) or any(
            isinstance(n, ast.Attribute) and n.attr == target for n in ast.walk(tree)):
        raise Unsupported('target_callers_or_references')
    if any(isinstance(n, ast.ImportFrom) and any(a.name == '*' for a in n.names)
           for n in ast.walk(tree)):
        raise Unsupported('star_import')
    if any(isinstance(n, ast.Name) and n.id in {
        'eval', 'exec', 'globals', 'locals', '__builtins__', 'setattr', 'getattr',
    } for n in ast.walk(tree)):
        raise Unsupported('dynamic_names')
    bound = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    bound.update(n.arg for n in ast.walk(tree) if isinstance(n, ast.arg))
    bound.update(n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    bound.update(n.name for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.name)
    for n in ast.walk(tree):
        if isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name:
            bound.add(n.name)
        if isinstance(n, ast.MatchMapping) and n.rest:
            bound.add(n.rest)
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            bound.update(a.asname or a.name.split('.')[0] for a in n.names)
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)
               and not n.bases and not n.keywords and not n.decorator_list
               and not any(isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and x.name == '__new__' for x in n.body)
               and not any(isinstance(x, ast.Attribute) and x.attr == '__class__'
                           for x in ast.walk(n))}
    # A class name must have exactly one declaration and no rebinding/import.
    for name in list(classes):
        definitions = sum(isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                          and n.name == name or isinstance(n, ast.Name)
                          and isinstance(n.ctx, ast.Store) and n.id == name
                          or isinstance(n, ast.arg) and n.arg == name
                          or isinstance(n, ast.alias) and (n.asname or n.name.split('.')[0]) == name
                          for n in ast.walk(tree))
        if definitions != 1:
            del classes[name]
    stores = Counter(n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store))
    values = {}
    parameters = {}
    for a in [*f.args.posonlyargs, *f.args.args, *f.args.kwonlyargs]:
        if stores[a.arg] == 0 and isinstance(a.annotation, ast.Name) and a.annotation.id in SCALARS:
            parameters[a.arg] = a.annotation.id
    for n in nodes:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            if stores[n.targets[0].id] == 1:
                values[n.targets[0].id] = n.value

    def infer(n, seen=frozenset()):
        if isinstance(n, ast.Constant):
            if n.value is None:
                return 'None'
            t = type(n.value).__name__
            if t in SCALARS:
                return t
        if isinstance(n, ast.JoinedStr):
            return 'str'
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            t = infer(n.operand, seen)
            if t in {'int', 'float', 'complex'}:
                return t
        if isinstance(n, ast.Name) and n.id in values and n.id not in seen:
            t = infer(values[n.id], seen | {n.id})
            if t in SCALARS:  # Mutable containers may have untracked writes.
                return t
        if isinstance(n, ast.Name) and n.id in parameters:
            return parameters[n.id]
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
            return 'bool'
        if isinstance(n, ast.Compare):
            if all(isinstance(op, (ast.Is, ast.IsNot, ast.In, ast.NotIn)) for op in n.ops):
                return 'bool'
            operand_types = [infer(e, seen) for e in [n.left, *n.comparators]]
            if all(t in SCALARS for t in operand_types):
                return 'bool'
        if isinstance(n, ast.BoolOp):
            ts = [infer(e, seen) for e in n.values]
            if len(set(ts)) == 1:
                return ts[0]
        if isinstance(n, ast.BinOp):
            left, right = infer(n.left, seen), infer(n.right, seen)
            if isinstance(n.op, ast.Add) and left == right and left in {'str', 'bytes'}:
                return left
            if isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)) and left in {'int', 'float'} and right in {'int', 'float'}:
                return 'float' if isinstance(n.op, ast.Div) or 'float' in {left, right} else 'int'
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            if n.func.id in SCALARS and n.func.id not in bound:
                return n.func.id
            if n.func.id not in bound:
                if n.func.id in {'isinstance', 'issubclass', 'hasattr', 'all', 'any', 'callable'}:
                    return 'bool'
                if n.func.id == 'len':
                    return 'int'
            if n.func.id in classes:
                return n.func.id
        if isinstance(n, ast.List) and n.elts:
            types = [infer(e, seen) for e in n.elts]
            if len(set(types)) == 1:
                return f'List[{types[0]}]'
        if isinstance(n, ast.ListComp):
            return f'List[{infer(n.elt, seen)}]'
        if isinstance(n, ast.Dict) and n.keys and all(k is not None for k in n.keys):
            keys = [infer(e, seen) for e in n.keys]
            vals = [infer(e, seen) for e in n.values]
            if len(set(keys)) == len(set(vals)) == 1:
                return f'Dict[{keys[0]}, {vals[0]}]'
        raise Unsupported('return_type_not_verified')

    returns = [n for n in nodes if isinstance(n, ast.Return)]
    if any(n.value is None for n in returns):
        raise Unsupported('bare_return')
    types = [infer(n.value) for n in returns]
    if len(set(types)) != 1:
        raise Unsupported('heterogeneous_returns')
    return tree, f, returns, types[0], infer, classes


def edit(code, edits):
    # AST offsets are UTF-8 bytes, not Python character indices.
    lines = code.encode().splitlines(keepends=True)
    offsets, total = [], 0
    for line in lines:
        offsets.append(total)
        total += len(line)
    data = code.encode()
    spans = []
    for n, replacement in edits:
        spans.append((offsets[n.lineno - 1] + n.col_offset,
                      offsets[n.end_lineno - 1] + n.end_col_offset, replacement.encode()))
    for start, end, value in sorted(spans, reverse=True):
        data = data[:start] + value + data[end:]
    result = data.decode()
    parse(result)
    return result


def transform_code(code, target, operation, expected_type):
    tree, f, returns, old_type, infer, classes = prepare(code, target)
    if canonical(old_type) != canonical(expected_type):
        raise Unsupported('source_label_not_verified')
    # Remove the target's now-stale prose rather than inventing a replacement.
    edits = [(f.body[0], '')] if ast.get_docstring(f) is not None else []
    if operation in {'wrap-list', 'wrap-dict'}:
        for n in returns:
            expression = ast.get_source_segment(code, n.value)
            text = f'[({expression})]' if operation == 'wrap-list' else f'{{"value": ({expression})}}'
            edits.append((n.value, text))
        label = f'List[{expected_type}]' if operation == 'wrap-list' else f'Dict[str, {expected_type}]'
    elif operation == 'element-float':
        for n in returns:
            if not isinstance(n.value, ast.List) or not n.value.elts or not all(
                    isinstance(e, ast.Constant) and isinstance(e.value, str) for e in n.value.elts):
                raise Unsupported('not_literal_string_list')
            edits.append((n.value, '[' + ', '.join(str(float(i)) for i, _ in enumerate(n.value.elts)) + ']'))
        label = 'List[float]'
    elif operation == 'instance-class':
        for n in returns:
            e = n.value
            if not isinstance(e, ast.Call) or not isinstance(e.func, ast.Name) or e.func.id not in classes:
                raise Unsupported('not_resolved_plain_class_constructor')
            if e.args or e.keywords:
                raise Unsupported('constructor_argument_effects')
            edits.append((e, e.func.id))
        label = f'Type[{expected_type}]'
    else:
        raise ValueError(operation)
    if canonical(label) == canonical(expected_type):
        raise Unsupported('unchanged_label')
    return edit(code, edits), normalize_type_label(label), ast.dump(f, include_attributes=False)


def augment(row, operation):
    if row.get('target_scope') != 'return':
        raise Unsupported('not_return_target')
    if 'evidence_bundle' in row:
        raise Unsupported('bundle_requires_synchronized_ast_relations')
    target = row['target_function'].split('.')[-1]
    code, label, original = transform_code(row['interprocedural_slice'], target, operation, row['label'])
    result = copy.deepcopy(row)
    result['interprocedural_slice'] = code
    for c in result['recommendation_types']:
        definition = c['definition']
        if not re.search(r'\b' + re.escape(target) + r'\b', definition):
            continue
        try:
            changed, copy_label, fingerprint = transform_code(definition, target, operation, row['label'])
        except Unsupported as e:
            raise Unsupported('ambiguous_candidate_copy') from e
        if fingerprint != original or label != copy_label:
            raise Unsupported('incompatible_candidate_copy')
        c['definition'] = changed
    result['label'] = label
    result['id'] = row['id'] + f'::synthetic:{POLICY}:{operation}'
    result['input'] = format_input(result['target_name'], result['target_function'],
                                   result['target_scope'], code, result['recommendation_types'])
    result['type_intervention'] = dict(policy=POLICY, parent_id=row['id'],
                                     operation=operation, original_label=row['label'], label=label,
                                     verification='bounded-static-expression-v1')
    return result


def build(source, output, seed=13):
    source, output = Path(source), Path(output)
    if output.exists():
        raise FileExistsError(output)
    hashes = {s: sha256(source / f'{s}.jsonl') for s in ('train', 'validation', 'test')}
    manifest = json.loads((source / 'manifest.json').read_text())
    if any(manifest['output'][s]['sha256'] != hashes[s] for s in hashes):
        raise ValueError('Source manifest/hash mismatch')
    output.mkdir(parents=True, exist_ok=False)
    counts = Counter()
    labels = Counter()
    ids = set()
    with (source / 'train.jsonl').open() as inp, (output / 'train.jsonl').open('w') as dest, \
            (output / 'synthetic_pairs.jsonl').open('w') as pairs:
        for line in inp:
            row = json.loads(line)
            if row['id'] in ids:
                raise ValueError('Duplicate source ID')
            ids.add(row['id'])
            dest.write(line)
            counts['original_rows'] += 1
            # At most one synthetic row per parent; stable operation order.
            operations = sorted(OPERATIONS, key=lambda op: hashlib.sha256(
                f'{seed}:{row["id"]}:{op}'.encode()).hexdigest())
            reasons = []
            accepted = False
            for op in operations:
                try:
                    changed = augment(row, op)
                except Unsupported as e:
                    reasons.append(str(e))
                    counts[f'rejected_attempt:{op}:{e}'] += 1
                    if str(e) not in {'not_literal_string_list', 'not_resolved_plain_class_constructor',
                                      'constructor_argument_effects', 'unchanged_label'}:
                        break  # Other failures are independent of the operation.
                    continue
                if changed['id'] in ids:
                    raise ValueError('Synthetic ID collision')
                ids.add(changed['id'])
                dest.write(json.dumps(changed, ensure_ascii=False) + '\n')
                pairs.write(json.dumps(changed['type_intervention'] | {'id': changed['id']}) + '\n')
                counts['synthetic_rows'] += 1
                counts[f'operation:{op}'] += 1
                labels[changed['label']] += 1
                accepted = True
                break
            if not accepted:
                counts['skipped_rows'] += 1
                counts[f'skipped:{reasons[0]}'] += 1
            if counts['original_rows'] % 5000 == 0:
                print(json.dumps(dict(counts)), flush=True)
    for split in ('validation', 'test'):
        shutil.copyfile(source / f'{split}.jsonl', output / f'{split}.jsonl')
    if not counts['synthetic_rows']:
        raise ValueError('No verified synthetic rows')
    result = dict(policy=POLICY, seed=seed, source_dir=str(source.resolve()), counts=dict(counts),
                  source_splits=manifest['output'], output_hashes={s: sha256(output / f'{s}.jsonl') for s in hashes},
                  synthetic_label_counts=dict(labels), code_sha256=sha256(Path(__file__)),
                  limitations=['Return targets only; no global execution-equivalence guarantee.',
                               'Synthetic labels follow an explicit concrete annotation policy, not unique author intent.',
                               'Candidates/ranking are frozen; bundles and unresolved copies are skipped.'])
    if any(sha256(source / f'{s}.jsonl') != hashes[s] for s in hashes):
        raise ValueError('Source changed during generation')
    (output / 'type_intervention_audit.json').write_text(json.dumps(result, indent=2) + '\n')
    derived = copy.deepcopy(manifest)
    derived['augmentation'] = dict(policy=POLICY, seed=seed, source_dir=str(source.resolve()))
    for s in hashes:
        derived['output'][s]['sha256'] = result['output_hashes'][s]
    derived['output']['train']['rows'] = counts['original_rows'] + counts['synthetic_rows']
    (output / 'manifest.json').write_text(json.dumps(derived, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=13)
    args = parser.parse_args()
    print(json.dumps(build(args.data_dir, args.output_dir, args.seed), indent=2), flush=True)


if __name__ == '__main__':
    main()
