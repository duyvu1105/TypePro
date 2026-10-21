"""Frozen full-KB validation for whole-slice lexical candidate evidence."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import tarfile
from time import perf_counter
from unittest.mock import patch

from typepro.analysis import candidate_policy as scoring
from typepro.analysis.ast_context_slicer import FunctionCatalog
from typepro.analysis.project_index import scan_project
from typepro.analysis.project_kb import top_project_types, target_member_query
from typepro.audit.candidate_symbol import cached_scoring, masked_function, rank, sha256, target


def identity(row):
    return (row['id'].rsplit(':', 2)[0], row['target_function'], row['target_name'], row['target_scope'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--old-dataset', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((args.dataset / 'manifest.json').read_text())
    data_path = args.dataset / 'validation.jsonl'
    assert sha256(data_path) == manifest['output']['validation']['sha256']
    selection = json.loads((args.artifacts / 'selection.json').read_text())
    selected_projects = {p['project'] for p in selection['projects']}
    rows = [row for line in data_path.open() if (row := json.loads(line))['project'] in selected_projects]
    old_rows = defaultdict(list)
    if args.old_dataset:
        old_path = args.old_dataset / 'validation.jsonl'
        old_manifest = json.loads((args.old_dataset / 'manifest.json').read_text())
        assert sha256(old_path) == old_manifest['output']['validation']['sha256']
        for line in old_path.open():
            row = json.loads(line)
            if row['project'] in selected_projects:
                old_rows[identity(row)].append(row)
    projects = {}
    for entry in selection['projects']:
        slug = entry['project'].replace('/', '__')
        kb_file = args.artifacts / (slug + '.json')
        archive = args.artifacts / (slug + '.tar.gz')
        root = args.artifacts / 'repos' / slug
        assert sha256(kb_file) == entry['kb_sha256']
        assert sha256(archive) == entry['source_archive_sha256']
        # Confirm local Python sources match the pinned archive, without executing them.
        with tarfile.open(archive) as bundle:
            for member in bundle.getmembers():
                if member.isfile() and member.name.endswith('.py'):
                    relative = Path(*Path(member.name).parts[1:])
                    assert '..' not in relative.parts
                    assert (root / relative).read_bytes() == bundle.extractfile(member).read()
        parsed, failures = scan_project(root)
        assert not failures
        projects[entry['project']] = (root, json.loads(kb_file.read_text()), FunctionCatalog(parsed, root), entry)
    variants = [('symbol_v2', scoring.SYMBOL_POLICY, 0, 0),
                ('visible_only', scoring.POLICY, 2, 0),
                ('overlap_only', scoring.POLICY, 0, 1),
                ('combined', scoring.POLICY, 2, 1)]
    totals = defaultdict(Counter)
    project_counts = Counter()
    retained = []
    baseline_equal = 0
    start = perf_counter()
    with (args.output_dir / 'rows.jsonl').open('w') as output:
        for i, row in enumerate(rows, 1):
            root, kb, catalog, entry = projects[row['project']]
            assert row['source_commit'] == entry['commit']
            relative = row['id'].rsplit(':', 2)[0].split(':repos/' + row['project'] + '/', 1)[1]
            path = (root / relative).resolve()
            assert path.is_relative_to(root.resolve())
            fn = target(catalog.trees[str(path)], row['target_function'])
            assert fn is not None
            fn = masked_function(fn, row)
            retained.append(fn)  # Catalog binding caches use scope identity.
            evidence = scoring.source_evidence(catalog, path, fn, row['target_name'], row['target_scope'], kb['records'])
            members = target_member_query(fn, row['target_name']) if row['target_scope'] == 'arg' else None
            from typepro.analysis.target_context import MASK
            code = row['interprocedural_slice'].replace('<mask>', MASK)
            outputs = {}
            # Shared pure helper memoization accelerates ablations; not a timing benchmark.
            with cached_scoring():
                for name, policy, visible, overlap in variants:
                    with patch.dict(scoring.WEIGHTS, name_visible=visible, lexical_overlap=overlap):
                        outputs[name] = top_project_types(kb, row['target_name'], code,
                            target_function=row['target_function'], target_scope=row['target_scope'],
                            target_members=members, evidence=evidence, policy=policy)
            # Gold labels first enter the audit after all selectors have finished.
            ranks = {name: rank(cs, row['label']) for name, cs in outputs.items()}
            baseline_equal += [c['qualified_name'] for c in outputs['symbol_v2']] == [
                c.get('qualified_name', c['type']) for c in row['recommendation_types']]
            for name, r in ranks.items():
                m = totals[name]
                m['rows'] += 1
                m['hits'] += r is not None
                m['top1'] += r == 1
                m['rr_sum'] += 1 / r if r else 0
                m['gained_vs_v2'] += r is not None and ranks['symbol_v2'] is None
                m['lost_vs_v2'] += r is None and ranks['symbol_v2'] is not None
            previous = old_rows.get(identity(row), [])
            old_rank = None
            if len(previous) == 1 and previous[0]['label'] == row['label']:
                old_rank = rank(previous[0]['recommendation_types'], row['label'])
                for name, current_rank in {**ranks, 'saved_v20': old_rank}.items():
                    m = totals['paired_v20_' + name]
                    m['rows'] += 1
                    m['hits'] += current_rank is not None
                    m['top1'] += current_rank == 1
                    m['rr_sum'] += 1 / current_rank if current_rank else 0
            project_counts[row['project']] += 1
            output.write(json.dumps(dict(id=row['id'], ranks=ranks, saved_v20_rank=old_rank,
                candidates={name: [dict(qualified_name=c['qualified_name'], score=c['score'],
                                       components=c['score_components']) for c in cs]
                            for name, cs in outputs.items()})) + '\n')
            if i % 10 == 0:
                print(json.dumps({'processed': i, 'total': len(rows), 'hits': {
                    name: totals[name]['hits'] for name, *_ in variants}}), flush=True)
    for m in totals.values():
        m['coverage'] = m['hits'] / m['rows']
        m['mrr'] = m['rr_sum'] / m['rows']
    summary = dict(policy=scoring.POLICY, weights=scoring.WEIGHTS, metrics=dict(totals),
                   projects=dict(project_counts), selection=selection,
                   baseline_v2_matches_saved_top10=baseline_equal,
                   validation_sha256=sha256(data_path), seconds=perf_counter() - start,
                   scope='Complete pinned KBs and complete pinned source for three fixed validation projects; all their validation rows. Ablations use production selection and rendering. Shared pure caches mean audit elapsed time is not a production performance benchmark. Saved v20 comparison uses matched target identities. This subset is not full-dataset recall or model accuracy.')
    (args.output_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
