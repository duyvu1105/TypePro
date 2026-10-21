"""Compare fixed v1/v2 selectors on pinned full KBs or exported slice pools.

No labels enter selection. Slice-pool results are diagnostic, not full-KB
recall. This command never modifies the source datasets or executes project code.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
from collections import Counter, defaultdict
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from typepro.analysis.ast_context_slicer import FunctionCatalog, FUNCTIONS
from typepro.analysis.candidate_policy import LEGACY_POLICY, SYMBOL_POLICY as POLICY, MIN_SCORE, source_evidence, score_candidate
from typepro.analysis.export_slices import add_parent_links, enclosing_class_path
from typepro.analysis.project_index import scan_project
from typepro.analysis.project_kb import top_project_types, target_member_query
from typepro.analysis.target_context import MASK, mask_definition


@contextmanager
def cached_scoring():
    """Reuse pure string/float helpers across variants of one fixed row.

    No scores, evidence, mutable ASTs or selected records are cached. The
    actual production selectors still run, including reduction and rendering.
    """
    from typepro.analysis import candidate_policy, project_kb
    targets = [(project_kb, 'mask_definition'), (candidate_policy, 'structural_text'),
               (candidate_policy, 'bm25_similarity')]
    originals = [(module, name, getattr(module, name)) for module, name in targets]
    try:
        for module, name, function in originals:
            setattr(module, name, lru_cache(maxsize=None)(function))
        yield
    finally:
        for module, name, function in originals:
            setattr(module, name, function)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def target(tree, name, *, allow_short=False):
    add_parent_links(tree)
    found = [n for n in ast.walk(tree) if isinstance(n, FUNCTIONS)
             and '.'.join(filter(None, (enclosing_class_path(n), n.name))) == name]
    if not found and allow_short:
        found = [n for n in ast.walk(tree) if isinstance(n, FUNCTIONS) and n.name == name.rsplit('.', 1)[-1]]
    return found[0] if len(found) == 1 else None


def masked_function(fn, row):
    # Parent links are not part of the function; copying them duplicates the
    # entire source module for every target.
    parent = getattr(fn, 'parent', None)
    fn = copy.deepcopy(fn, {id(parent): None} if parent is not None else {})
    if row['target_scope'] == 'return':
        fn.returns = ast.Name(id=MASK, ctx=ast.Load())
    else:
        for arg in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs,
                    *([fn.args.vararg] if fn.args.vararg else []),
                    *([fn.args.kwarg] if fn.args.kwarg else [])]:
            if arg.arg == row['target_name']:
                arg.annotation = ast.Name(id=MASK, ctx=ast.Load())
    return fn


def selections(row, kb, catalog, path, fn, *, replay=False):
    args = (catalog, path, fn, row['target_name'], row['target_scope'], kb['records'])
    old = source_evidence(*args, policy=LEGACY_POLICY)
    new = source_evidence(*args)
    symbol_only = {**old, 'symbol': new['symbol']}
    variants = [('v1', old, LEGACY_POLICY), ('symbol_only', symbol_only, POLICY),
                ('import_only', new, LEGACY_POLICY), ('combined', new, POLICY)]
    # Restore the internal mask spelling used before export render_masks().
    code = row['interprocedural_slice'].replace('<mask>', MASK)
    members = target_member_query(fn, row['target_name']) if row['target_scope'] == 'arg' else None
    if replay:
        # Pre-render diagnostic ranking. Already-reduced definitions cannot
        # reproduce selection/rendering against original full definitions.
        outputs = {}
        definitions = [(c, mask_definition(c['definition'], row['target_function'],
                       row['target_name'], row['target_scope'])) for c in kb['records']]
        for name, evidence, policy in variants:
            ranked = []
            for c, definition in definitions:
                score, parts = score_candidate(c, definition, row['target_name'], code, members,
                                               evidence, policy=policy)
                if score >= MIN_SCORE:
                    ranked.append(dict(name=c['name'], qualified_name=c['qualified_name'],
                                       score=score, score_components=parts))
            ranked.sort(key=lambda c: (-c['score'], c['qualified_name'].casefold()))
            outputs[name] = ranked[:10]
        return outputs
    return {name: top_project_types(kb, row['target_name'], code,
                target_function=row['target_function'], target_scope=row['target_scope'],
                target_members=members, evidence=evidence, policy=policy)
            for name, evidence, policy in variants}


def rank(candidates, label):
    normalize = lambda s: ''.join(s.split())
    return next((i for i, c in enumerate(candidates, 1)
                 if normalize(label) in {normalize(c.get('name', c.get('type', ''))),
                                         normalize(c.get('qualified_name', ''))}), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--old-dataset', type=Path)
    parser.add_argument('--artifacts', type=Path, help='Full KB/source folder containing selection.json and repos/')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError('Use a new output directory')
    args.output_dir.mkdir(parents=True)
    path = args.dataset / 'validation.jsonl'
    manifest = json.loads((args.dataset / 'manifest.json').read_text())
    if sha256(path) != manifest['output']['validation']['sha256']:
        raise ValueError('Validation hash differs from manifest')
    rows = [json.loads(s) for s in path.open()]
    key = lambda r: (r['id'].rsplit(':', 2)[0], r['target_function'], r['target_name'], r['target_scope'])
    old_rows = defaultdict(list)
    if args.old_dataset:
        for s in (args.old_dataset / 'validation.jsonl').open():
            row = json.loads(s)
            old_rows[key(row)].append(row)
    projects = {}
    selection = None
    if args.artifacts:
        selection = json.loads((args.artifacts / 'selection.json').read_text())
        for entry in selection['projects']:
            slug = entry['project'].replace('/', '__')
            kb_file = args.artifacts / f'{slug}.json'
            archive = args.artifacts / f'{slug}.tar.gz'
            assert sha256(kb_file) == entry['kb_sha256']
            assert sha256(archive) == entry['source_archive_sha256']
            root = args.artifacts / 'repos' / slug
            parsed, failures = scan_project(root)
            if failures:
                raise ValueError(f'Source parse failures: {slug}')
            projects[entry['project']] = (root, json.loads(kb_file.read_text()), FunctionCatalog(parsed, root), entry)
        rows = [r for r in rows if r['project'] in projects]
    metrics = defaultdict(Counter)
    skipped = []
    baseline_equal = 0
    retained_functions = []  # Catalog binding caches use scope identity.
    with (args.output_dir / 'rows.jsonl').open('w') as output:
        for index, row in enumerate(rows, 1):
            if args.artifacts:
                root, kb, catalog, entry = projects[row['project']]
                assert row['source_commit'] == entry['commit']
                relative = row['id'].rsplit(':', 2)[0].split(':repos/' + row['project'] + '/', 1)[1]
                source_path = (root / relative).resolve()
                assert source_path.is_relative_to(root.resolve())
                tree = catalog.trees.get(str(source_path))
            else:
                # Fixed union of previously exported candidates, identical for
                # all selectors; reduced definitions cannot replace a full KB.
                source_path = (args.output_dir / 'slice.py').resolve()
                try:
                    tree = ast.parse(row['interprocedural_slice'].replace('<mask>', MASK))
                except (SyntaxError, ValueError):
                    skipped.append(dict(id=row['id'], reason='slice_parse_failed'))
                    continue
                catalog = FunctionCatalog([(source_path, '', ast.unparse(tree), tree)])
                pool = {}
                previous = old_rows.get(key(row), [])
                if args.old_dataset and (len(previous) != 1 or previous[0]['interprocedural_slice'] != row['interprocedural_slice']):
                    skipped.append(dict(id=row['id'], reason='unmatched_or_changed_slice'))
                    continue
                for r in [row, *previous]:
                    for c in r['recommendation_types']:
                        qualified = c.get('qualified_name') or c['type']
                        pool.setdefault(qualified.casefold(), dict(c, name=c['type'], qualified_name=qualified,
                                                                  kind=c.get('kind', 'class'), source=c.get('source', 'unknown')))
                kb = {'records': list(pool.values())}
            fn = target(tree, row['target_function'], allow_short=not args.artifacts) if tree is not None else None
            if fn is None:
                skipped.append(dict(id=row['id'], reason='ambiguous_or_missing_target'))
                continue
            fn = masked_function(fn, row)
            if args.artifacts:
                retained_functions.append(fn)
            with cached_scoring():
                selected = selections(row, kb, catalog, source_path, fn, replay=not args.artifacts)
            # Labels are first consulted here, after all variants selected.
            ranks = {name: rank(cs, row['label']) for name, cs in selected.items()}
            old_hit = ranks['v1'] is not None
            for name, r in ranks.items():
                m = metrics[name]
                m['rows'] += 1
                m['hits'] += r is not None
                m['rr_sum'] += 1 / r if r else 0
                m['gained'] += r is not None and not old_hit
                m['lost'] += r is None and old_hit
                m['top10_changed'] += [c['qualified_name'] for c in selected[name]] != [c['qualified_name'] for c in selected['v1']]
            baseline_equal += [c['qualified_name'] for c in selected['v1']] == [c.get('qualified_name', c['type']) for c in row['recommendation_types']]
            output.write(json.dumps(dict(id=row['id'], ranks=ranks, candidates={
                name: [dict(name=c['name'], qualified_name=c['qualified_name'], score=c['score'],
                            score_components=c['score_components']) for c in cs]
                for name, cs in selected.items()})) + '\n')
            if index % 20 == 0:
                print(json.dumps(dict(processed=index, total=len(rows), hits={n: m['hits'] for n, m in metrics.items()})), flush=True)
    for m in metrics.values():
        m['coverage'] = m['hits'] / m['rows']
        m['mrr'] = m['rr_sum'] / m['rows']
    summary = dict(policy=POLICY, mode='full_kb' if args.artifacts else 'exported_union_pool',
                   dataset_validation_sha256=sha256(path), selection=selection,
                   metrics=dict(metrics), selected_rows=len(rows), skipped=skipped,
                   baseline_matches_saved_top10=baseline_equal,
                   limitations='Full-KB subset is three projects; exported pools are pre-render ranking with reduced definitions and incomplete source/callers. Neither measures model accuracy.')
    (args.output_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
