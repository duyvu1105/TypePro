"""Transport known return contracts through checked wrapper transformations.

The source label is an assumed contract, not an independently inferred fact.
Only the transport and resolvable local callers are checked. Dataset code is
never executed. This does not establish whole-repository correctness.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import copy
import hashlib
from itertools import islice
import json
import multiprocessing
from pathlib import Path, PurePosixPath
import re
import shutil

import libcst as cst
from libcst.metadata import MetadataWrapper, ParentNodeProvider, ScopeProvider

from typepro.data.preprocess import format_input
from typepro.shared.type_labels import normalize_type_label
from typepro.training.type_changing import Unsupported, sha256

POLICY = 'return-contract-transport-v2'
MASK = '__TYPEPRO_CONTRACT_MASK__'
OPERATIONS = ('wrap-list', 'wrap-dict')


def parsed(code):
    if MASK in code:
        raise Unsupported('sentinel_collision')
    try:
        return ast.parse(code.replace('<mask>', MASK))
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise Unsupported('unparseable_code') from exc


def lexical(node):
    """Walk the function's own statements, excluding nested execution scopes."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield child
        yield from lexical(child)


def exits(body):
    """Sufficient, intentionally incomplete proof of no normal fallthrough."""
    if not body:
        return False
    last = body[-1]
    if isinstance(last, (ast.Return, ast.Raise)):
        return True
    if isinstance(last, ast.If):
        return exits(last.body) and exits(last.orelse)
    if isinstance(last, ast.Try):
        if exits(last.finalbody):
            return True
        return (exits(last.body) and not last.orelse
                and all(exits(h.body) for h in last.handlers))
    return False


def allows_none(label):
    def check(n):
        if isinstance(n, ast.Constant):
            return n.value is None
        if isinstance(n, ast.Name):
            return n.id in {'Any', 'object'}
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr):
            return check(n.left) or check(n.right)
        if isinstance(n, ast.Subscript):
            name = ast.unparse(n.value).removeprefix('typing.')
            if name == 'Optional':
                return True
            if name == 'Union':
                return any(check(e) for e in (n.slice.elts if isinstance(n.slice, ast.Tuple) else [n.slice]))
        return False
    return check(ast.parse(normalize_type_label(label), mode='eval').body)


def qualified_ast(tree):
    result = {}
    def walk(node, prefix=()):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = (*prefix, child.name)
                result[child] = '.'.join(name)
                walk(child, name)
            else:
                walk(child, prefix)
    walk(tree)
    return result


def select_function(tree, function, required=True, allow_unannotated=False):
    short = function.split('.')[-1]
    qualified = qualified_ast(tree)
    candidates = [n for n, q in qualified.items() if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and (q == function or q == short)]
    masked = [n for n in candidates if isinstance(n.returns, ast.Name) and n.returns.id == MASK]
    if not masked and allow_unannotated and len(candidates) == 1 and candidates[0].returns is None:
        return candidates[0]
    if len(masked) != 1:
        if required or masked or candidates:
            raise Unsupported('ambiguous_or_unmasked_target_copy')
        return None
    return masked[0]


def signature(f):
    # Parameter names/defaults/annotations identify copies; bodies can be reduced
    # differently by the exporter and must each receive their own return edits.
    return ast.dump(f.args, include_attributes=False)


def inspect_target(tree, f, label):
    if isinstance(f, ast.AsyncFunctionDef) or f.decorator_list or f.name.startswith('__'):
        raise Unsupported('special_or_decorated_target')
    nodes = list(lexical(f))
    if any(isinstance(n, (ast.Yield, ast.YieldFrom, ast.Await)) for n in nodes):
        raise Unsupported('generator_or_async_target')
    returns = [n for n in nodes if isinstance(n, ast.Return)]
    if not returns:
        raise Unsupported('no_explicit_return_or_stub')
    fallthrough = not exits(f.body)
    if (fallthrough or any(n.value is None for n in returns)) and not allows_none(label):
        raise Unsupported('none_path_outside_source_contract')
    if any(isinstance(n.value, ast.Constant) and n.value.value is Ellipsis for n in returns):
        raise Unsupported('ellipsis_stub')
    return fallthrough


def transform(code, function, label, operation, *, expected_signature=None,
              require_target=True, external_global=False, trusted_unannotated=False):
    """Edit returns and binding-resolved direct calls; reject escaping references."""
    if operation not in OPERATIONS:
        raise ValueError(operation)
    short = function.split('.')[-1]
    tree = parsed(code)
    f = select_function(tree, function, require_target, allow_unannotated=trusted_unannotated)
    sig = signature(f) if f else None
    if f and expected_signature is not None and sig != expected_signature:
        raise Unsupported('candidate_signature_mismatch')
    fallthrough = inspect_target(tree, f, label) if f else False
    possible = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == short and isinstance(n.ctx, ast.Load)
                or isinstance(n, ast.Attribute) and n.attr == short]
    if f is None and not possible:
        return code, dict(changed=False, callers=0, returns=0, docstrings=0), None
    if any(isinstance(n, (ast.Global, ast.Nonlocal)) for n in ast.walk(tree)):
        raise Unsupported('global_or_nonlocal')
    if any(isinstance(n, ast.ImportFrom) and any(a.name == '*' for a in n.names) for n in ast.walk(tree)):
        raise Unsupported('star_import')
    if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {
            'eval', 'exec', 'getattr', 'setattr', 'globals', 'locals', 'vars', '__import__'} for n in ast.walk(tree)):
        raise Unsupported('dynamic_resolution')
    if any(isinstance(n, ast.Attribute) and n.attr == short and isinstance(n.ctx, (ast.Store, ast.Del))
           for n in ast.walk(tree)):
        raise Unsupported('target_attribute_reassigned')
    try:
        wrapper = MetadataWrapper(cst.parse_module(code.replace('<mask>', MASK)))
        scopes = wrapper.resolve(ScopeProvider)
        parents = wrapper.resolve(ParentNodeProvider)
    except Exception as exc:
        # Parser/metadata failures are unsupported source, never partial edits.
        raise Unsupported('cst_metadata_failed') from exc

    def qualified(n):
        names = [n.name.value]
        p = parents.get(n)
        while p is not None:
            if isinstance(p, (cst.ClassDef, cst.FunctionDef)):
                names.append(p.name.value)
            p = parents.get(p)
        return '.'.join(reversed(names))

    matches = []
    class Find(cst.CSTVisitor):
        def visit_FunctionDef(self, n):
            if qualified(n) in {function, short} and (
                    n.returns and isinstance(n.returns.annotation, cst.Name) and n.returns.annotation.value == MASK
                    or trusted_unannotated and n.returns is None):
                matches.append(n)
    wrapper.module.visit(Find())
    selected = matches[0] if f else None
    if f and len(matches) != 1:
        raise Unsupported('cst_target_mismatch')
    calls = set()
    target_names = set()
    if selected:
        scope = scopes[selected]
        if type(scope).__name__ not in {'GlobalScope', 'ClassScope'}:
            raise Unsupported('nested_target_binding')
        assignments = [a for a in scope.assignments if a.name == short]
        if len(assignments) != 1 or assignments[0].node is not selected:
            raise Unsupported('reassigned_target_binding')
        for access in assignments[0].references:
            if len(access.referents) != 1:
                raise Unsupported('ambiguous_target_reference')
            parent = parents.get(access.node)
            if not isinstance(parent, cst.Call) or parent.func is not access.node:
                raise Unsupported('escaping_function_reference')
            calls.add(parent)
            target_names.add(access.node)

    class Inspect(cst.CSTVisitor):
        def visit_Name(self, n):
            if n.value != short or n in target_names or n not in scopes:
                return
            parent = parents.get(n)
            if isinstance(parent, cst.Attribute) and parent.attr is n:
                return
            if isinstance(parent, cst.FunctionDef) and parent.name is n:
                return
            # A candidate-only fragment may refer to a module function defined
            # in the primary slice. Only an unbound direct name can be linked.
            accesses = [a for a in scopes[n].accesses if a.node is n]
            if accesses and not accesses[0].referents:
                if external_global and isinstance(parent, cst.Call) and parent.func is n:
                    calls.add(parent)
                else:
                    raise Unsupported('unresolved_external_caller')
        def visit_Attribute(self, n):
            if n.attr.value != short:
                return
            # Resolve only explicit Class.method calls to this exact class.
            owner = parents.get(selected) if selected else None
            while owner is not None and not isinstance(owner, cst.ClassDef):
                owner = parents.get(owner)
            if owner is None or not isinstance(n.value, cst.Name) or n.value.value != owner.name.value:
                raise Unsupported('unresolved_method_reference')
            bindings = list(scopes[n.value][n.value.value])
            parent = parents.get(n)
            if len(bindings) != 1 or bindings[0].node is not owner or not isinstance(parent, cst.Call) or parent.func is not n:
                raise Unsupported('ambiguous_class_method_caller')
            calls.add(parent)
    wrapper.module.visit(Inspect())

    stats = dict(changed=bool(selected or calls), callers=len(calls), returns=0, docstrings=0,
                 implicit_none_paths=int(fallthrough))

    def wrap(expression):
        # A return's unparenthesized tuple must remain ONE list/dict value.
        expression=expression.with_changes(lpar=(cst.LeftParen(), *expression.lpar),
                                           rpar=(*expression.rpar, cst.RightParen()))
        if operation == 'wrap-list':
            return cst.List([cst.Element(expression)])
        return cst.Dict([cst.DictElement(cst.SimpleString('"value"'), expression)])

    class Rewrite(cst.CSTTransformer):
        def leave_Call(self, original, updated):
            if original in calls:
                key = cst.Integer('0') if operation == 'wrap-list' else cst.SimpleString('"value"')
                return cst.Subscript(updated, [cst.SubscriptElement(cst.Index(key))])
            return updated
        def leave_Return(self, original, updated):
            p = parents.get(original)
            while p is not None and not isinstance(p, cst.FunctionDef):
                p = parents.get(p)
            if p is selected:
                stats['returns'] += 1
                return updated.with_changes(value=wrap(updated.value or cst.Name('None')))
            return updated
        def leave_FunctionDef(self, original, updated):
            if original is not selected:
                return updated
            body = updated.body
            statements = list(body.body)
            first = statements[0] if statements else None
            # CST stores docstrings differently in indented/one-line suites.
            small = first.body[0] if isinstance(first, cst.SimpleStatementLine) and first.body else first
            if ast.get_docstring(f) is not None and isinstance(small, cst.Expr) and isinstance(small.value, (cst.SimpleString, cst.ConcatenatedString)):
                stats['docstrings'] += 1
                if isinstance(first, cst.SimpleStatementLine) and len(first.body) > 1:
                    statements[0] = first.with_changes(body=first.body[1:])
                else:
                    statements.pop(0)
            if fallthrough:
                ret = cst.Return(wrap(cst.Name('None')))
                statements.append(cst.SimpleStatementLine([ret]) if isinstance(body, cst.IndentedBlock) else ret)
            return updated.with_changes(body=body.with_changes(body=statements))

    result = wrapper.module.visit(Rewrite()).code.replace(MASK, '<mask>')
    new_tree = parsed(result)
    # Compile a copy with a harmless annotation placeholder; never run it.
    try:
        compile(new_tree, '<contract-intervention>', 'exec')
    except (SyntaxError, ValueError) as exc:
        raise Unsupported('noncompilable_export_fragment') from exc
    if selected and stats['returns'] == 0:
        raise Unsupported('no_return_transformed')
    return result, stats, sig


def candidate_from_target_file(row, candidate):
    """Verify an unannotated KB copy using exported file identity and qualname.

    Different project source roots (src/, lib/, etc.) may precede the importable
    module. Require the complete candidate qualname to equal one such suffix;
    matching only the class or function's short name is insufficient.
    """
    try:
        project = row['project']
        path = row['id'].split(':', 1)[1].rsplit(':', 2)[0]
        prefix = f'repos/{project}/'
        if not path.startswith(prefix):
            return False
        parts = list(PurePosixPath(path[len(prefix):]).with_suffix('').parts)
        if parts and parts[-1] == '__init__':
            parts.pop()
        function = row['target_function']
        owner = function.rsplit('.', 1)[0] if '.' in function else function
        qualified = candidate.get('qualified_name', '')
        return any(qualified == '.'.join([*parts[i:], owner]) for i in range(len(parts)))
    except (KeyError, IndexError, ValueError):
        return False


def augment(row, operation):
    if row.get('target_scope') != 'return':
        raise Unsupported('not_return_target')
    if 'evidence_bundle' in row:
        raise Unsupported('bundle_not_supported_by_v24_transport')
    label = normalize_type_label(row['label'])
    function = row['target_function']
    code, stats, sig = transform(row['interprocedural_slice'], function, label, operation)
    result = copy.deepcopy(row)
    copies = 0
    for candidate in result['recommendation_types']:
        definition = candidate['definition']
        short = function.split('.')[-1]
        if not re.search(r'\b' + re.escape(short) + r'\b', definition):
            continue
        try:
            changed, extra, _ = transform(definition, function, label, operation,
                                           expected_signature=sig, require_target=False,
                                           trusted_unannotated=candidate_from_target_file(row, candidate))
        except Unsupported as exc:
            raise Unsupported('candidate:' + str(exc)) from exc
        candidate['definition'] = changed
        if extra['changed']:
            copies += 1
            for key in ('callers', 'returns', 'docstrings', 'implicit_none_paths'):
                stats[key] = stats.get(key, 0) + extra.get(key, 0)
    result['interprocedural_slice'] = code
    result['label'] = normalize_type_label(f'List[{label}]' if operation == 'wrap-list' else f'Dict[str, {label}]')
    result['id'] = row['id'] + f'::synthetic:{POLICY}:{operation}'
    result['input'] = format_input(result['target_name'], function, 'return', code, result['recommendation_types'])
    result['type_intervention'] = dict(policy=POLICY, parent_id=row['id'], operation=operation,
                                     original_label=row['label'], label=result['label'],
                                     verification='assumed-source-contract+checked-wrapper-and-local-callers',
                                     stats=stats, synchronized_candidate_copies=copies)
    return result


def produce(item):
    """CPU worker: no dataset I/O, no tokenizer/model, no code execution."""
    row,seed=item
    rank=hashlib.sha256(f'{seed}:{row["id"]}'.encode()).hexdigest()
    operation=OPERATIONS[int(rank[-1],16)%2]
    try:
        return rank,augment(row,operation),None
    except Unsupported as exc:
        return rank,None,str(exc)


def build(source, output, seed=13, *, tokenizer=None, prompt_limit=6080,
          max_synthetic=5000, per_project=100, workers=1):
    source, output = Path(source), Path(output)
    if output.exists():
        raise FileExistsError(output)
    if max_synthetic < 1 or per_project < 1 or workers < 1:
        raise ValueError('Positive sample/project limits required')
    manifest = json.loads((source / 'manifest.json').read_text())
    initial = {s: sha256(source / f'{s}.jsonl') for s in ('train', 'validation', 'test')}
    if any(initial[s] != manifest['output'][s]['sha256'] for s in initial):
        raise ValueError('Source manifest/hash mismatch')
    output.mkdir(parents=True, exist_ok=False)
    counts, projects, labels, source_labels = Counter(), Counter(), Counter(), Counter()
    pool = output / 'synthetic_pool.jsonl.tmp'
    metadata = []
    source_ids = set()
    executor=ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) if workers>1 else None
    def results(inp):
        while batch:=list(islice(inp,128)):
            rows=[json.loads(line) for line in batch]
            items=[(row,seed) for row in rows]
            generated=executor.map(produce,items,chunksize=4) if executor else map(produce,items)
            yield from zip(rows,generated)
    try:
      with (source / 'train.jsonl').open() as inp, pool.open('wb') as spool:
        for row,(rank,changed,error) in results(inp):
            if row['id'] in source_ids:
                raise ValueError('Duplicate source ID')
            source_ids.add(row['id'])
            counts['original_rows'] += 1
            try:
                if error is not None:
                    raise Unsupported(error)
                if tokenizer is not None:
                    from typepro.shared.generative_chat import chat_token_ids
                    tokens = len(chat_token_ids(tokenizer, changed['input']))
                    if tokens > prompt_limit:
                        raise Unsupported('synthetic_prompt_over_budget')
                    changed['type_intervention']['prompt_tokens'] = tokens
            except Unsupported as exc:
                counts['skipped:' + str(exc)] += 1
            else:
                offset = spool.tell()
                encoded = (json.dumps(changed, ensure_ascii=False) + '\n').encode()
                spool.write(encoded)
                metadata.append((rank, row['id'], row.get('project', 'unknown'), offset, len(encoded)))
                counts['eligible_rows'] += 1
            if counts['original_rows'] % 5000 == 0:
                print(json.dumps(dict(counts)), flush=True)
    finally:
        if executor:
            executor.shutdown(wait=True,cancel_futures=True)
    selected = {}
    for rank, parent, project, offset, length in sorted(metadata):
        if len(selected) >= max_synthetic:
            counts['limited_by_total'] += 1
        elif projects[project] >= per_project:
            counts['limited_by_project'] += 1
        else:
            selected[parent] = (offset, length)
            projects[project] += 1
    seen = set(source_ids)
    with (source / 'train.jsonl').open() as inp, pool.open('rb') as spool, \
            (output / 'train.jsonl').open('w') as dest, \
            (output / 'synthetic_pairs.jsonl').open('w') as pairs:
        for line in inp:
            row = json.loads(line)
            dest.write(line if line.endswith('\n') else line + '\n')
            if row['id'] not in selected:
                continue
            offset, length = selected[row['id']]
            spool.seek(offset)
            text = spool.read(length).decode()
            changed = json.loads(text)
            if changed['id'] in seen:
                raise ValueError('Synthetic ID collision')
            seen.add(changed['id'])
            dest.write(text)
            pairs.write(json.dumps(changed['type_intervention'] | {'id': changed['id'], 'project': row.get('project')}) + '\n')
            counts['synthetic_rows'] += 1
            counts['operation:' + changed['type_intervention']['operation']] += 1
            for key, value in changed['type_intervention']['stats'].items():
                if key != 'changed':
                    counts['transformed:' + key] += value
            counts['synchronized_candidate_copies'] += changed['type_intervention']['synchronized_candidate_copies']
            labels[changed['label']] += 1
            source_labels[row['label']] += 1
    pool.unlink()
    for s in ('validation', 'test'):
        shutil.copyfile(source / f'{s}.jsonl', output / f'{s}.jsonl')
    output_hashes = {s: sha256(output / f'{s}.jsonl') for s in initial}
    if any(sha256(source / f'{s}.jsonl') != initial[s] for s in initial):
        raise ValueError('Source changed during generation')
    if not counts['synthetic_rows']:
        raise ValueError('No synthetic rows')
    audit = dict(policy=POLICY, seed=seed, source_dir=str(source.resolve()),
                 source_splits=manifest['output'], output_hashes=output_hashes,
                 code_sha256=sha256(Path(__file__)), counts=dict(counts),
                 projects=dict(projects), synthetic_label_counts=dict(labels), source_label_counts=dict(source_labels),
                 limits=dict(max_synthetic=max_synthetic, per_project=per_project, prompt_limit=prompt_limit),
                 workers=workers,
                 tokenizer=getattr(tokenizer, 'name_or_path', None),
                 readiness=dict(min_synthetic=2000, min_projects=20, min_source_labels=20,
                                passed=counts['synthetic_rows'] >= 2000 and len(projects) >= 20 and len(source_labels) >= 20
                                and tokenizer is not None),
                 assumptions=['Source labels are assumed valid return contracts; their semantic correctness is not re-proven.',
                              'Synthetic wrapper annotations are valid transported contracts, not uniquely identifiable author annotations.',
                              'Resolution checks apply to the exported sample, not unseen repository code.',
                              'Decorators, async, special methods, escaping/dynamic references and unresolved receivers are skipped.',
                              'Candidate order/ranking frozen; evidence bundles unsupported; no training is started by generation.'])
    (output / 'type_intervention_audit.json').write_text(json.dumps(audit, indent=2) + '\n')
    derived = copy.deepcopy(manifest)
    derived['augmentation'] = dict(policy=POLICY, seed=seed, source_dir=str(source.resolve()))
    for s in initial:
        derived['output'][s]['sha256'] = output_hashes[s]
    derived['output']['train']['rows'] = counts['original_rows'] + counts['synthetic_rows']
    (output / 'manifest.json').write_text(json.dumps(derived, indent=2) + '\n')
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=13)
    parser.add_argument('--max-synthetic', type=int, default=5000)
    parser.add_argument('--per-project', type=int, default=100)
    parser.add_argument('--workers', type=int, default=4, help='CPU AST workers; tokenizer stays in the parent')
    parser.add_argument('--model-name', default='Qwen/Qwen2.5-Coder-0.5B-Instruct')
    parser.add_argument('--input-length', type=int, default=6144)
    parser.add_argument('--label-length', type=int, default=64)
    args = parser.parse_args()
    if args.label_length < 1 or args.input_length <= args.label_length:
        parser.error('Require input_length > label_length > 0')
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.model_name, local_files_only=True)
    audit = build(args.data_dir, args.output_dir, args.seed, tokenizer=tokenizer,
                  prompt_limit=args.input_length - args.label_length,
                  max_synthetic=args.max_synthetic, per_project=args.per_project, workers=args.workers)
    print(json.dumps(audit, indent=2), flush=True)


if __name__ == '__main__':
    main()
