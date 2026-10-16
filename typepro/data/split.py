"""Select an exact-size test holdout from successfully preprocessed projects."""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

SPLITS = ('train', 'validation', 'test')


def load_test_projects(path):
    projects = [line.strip() for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not projects or any(not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', p) for p in projects):
        raise ValueError('Test project list must contain owner/repository identifiers')
    if len({p.casefold() for p in projects}) != len(projects):
        raise ValueError('Duplicate test projects (case insensitive)')
    return sorted(projects)


def stable_number(project, seed):
    return int(hashlib.sha1(f'{seed}:{project.casefold()}'.encode()).hexdigest()[:16], 16)


def choose_test_projects(available, preferred, count, seed):
    if count <= 0:
        raise ValueError('Test project count must be positive')
    canonical = {}
    for project in sorted(available):
        canonical.setdefault(project.casefold(), project)
    if len(canonical) < count:
        raise ValueError(f'Only {len(canonical)} projects have usable samples; cannot select {count} test projects')
    preferred_keys = {p.casefold() for p in preferred}
    rank = lambda p: (stable_number(p, seed + 1), p.casefold())
    retained = sorted((p for key, p in canonical.items() if key in preferred_keys), key=rank)[:count]
    extras = sorted((p for key, p in canonical.items() if key not in preferred_keys), key=rank)[:count - len(retained)]
    return sorted(retained + extras), sorted(extras)


def assign_projects(projects, test_projects, seed, validation_ratio):
    if not 0 <= validation_ratio < 1:
        raise ValueError('Validation ratio must be in [0, 1)')
    heldout = {p.casefold() for p in test_projects}
    return {
        project: 'test' if project.casefold() in heldout else (
            'validation' if stable_number(project, seed + 2) % 10000 < int(validation_ratio * 10000) else 'train'
        ) for project in projects
    }


def iter_output_rows(output_dir):
    for split in SPLITS:
        with (output_dir / f'{split}.jsonl').open(encoding='utf-8') as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


def prepare_project_holdout(work_dir, output_dir, project_list, count, seed, validation_ratio, project_from_row):
    # Scan with the SAME eligibility predicate as the writer. No output copy is made.
    from preprocess_generative import iter_records, project_name, record_fields
    preferred = load_test_projects(project_list)
    available = set()
    counts_by_project = Counter()
    for row in iter_records(work_dir / 'raw_slices'):
        if all(record_fields(row)):
            project = project_name(row)
            available.add(project)
            counts_by_project[project] += 1
    selected, extras = choose_test_projects(available, preferred, count, seed)
    mapping = assign_projects(available, selected, seed, validation_ratio)
    written_projects = {split: {p.casefold() for p, target in mapping.items() if target == split} for split in SPLITS}
    if any(not projects for projects in written_projects.values()):
        raise ValueError('Fixed project holdout requires nonempty train, validation and test splits')
    metadata = work_dir / 'metadata'
    original = json.loads((metadata / 'split_manifest.json').read_text(encoding='utf-8'))
    prepared_counts = Counter()
    prepared_projects = {split: set() for split in SPLITS}
    for split in SPLITS:
        for row in json.loads((metadata / f'{split}.json').read_text(encoding='utf-8')):
            project = project_from_row(row)
            target = assign_projects([project], selected, seed, validation_ratio)[project]
            prepared_counts[target] += 1
            prepared_projects[target].add(project.casefold())
    # The preprocessor consumes this small map and writes each final sample once.
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'project_split_map.json').write_text(json.dumps(mapping, indent=2), encoding='utf-8')
    available_keys = {p.casefold() for p in available}
    audit = {
        'split_profile': 'typepro_artifact_projects',
        'selection_policy': 'Prefer available artifact projects; fill deterministically from other processed projects',
        'test_project_list_sha256': hashlib.sha256(project_list.read_bytes()).hexdigest(),
        'requested_test_projects': count,
        'preferred_projects': preferred,
        'unavailable_preferred_projects': [p for p in preferred if p.casefold() not in available_keys],
        'retained_preferred_projects': [p for p in selected if p not in extras],
        'supplemented_projects': extras,
        'test_projects': selected,
        'missing_output_projects': [],
        'expected_written_counts': {split: sum(n for p, n in counts_by_project.items() if mapping[p] == split) for split in SPLITS},
        'seed': seed,
        'validation_project_ratio': validation_ratio,
        'original_split': original,
        'prepared_counts': {split: prepared_counts[split] for split in SPLITS},
        'prepared_projects': {split: len(projects) for split, projects in prepared_projects.items()},
        'written_projects': {split: len(projects) for split, projects in written_projects.items()},
        'scope_note': 'All available annotations in selected projects; adjusted benchmark, not the original 11,029 samples.',
    }
    (output_dir / 'test_projects.txt').write_text('\n'.join(selected) + '\n', encoding='utf-8')
    (output_dir / 'test_split_audit.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
    print(json.dumps({'test_project_count': len(selected), 'retained_artifact_projects': len(selected) - len(extras), 'supplemented_projects': len(extras)}, indent=2), flush=True)
    return audit
