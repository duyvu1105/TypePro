import json
from pathlib import Path

import pytest

from fixed_test_split import assign_projects, choose_test_projects, load_test_projects, resplit_completed_dataset, iter_output_rows
from prepare_dataset import project_from_row


def test_selection_prefers_available_artifact_and_fills_exact_count():
    available = [f'owner/repo{i}' for i in range(150)]
    preferred = ['owner/repo1', 'OWNER/repo2', 'owner/missing']
    selected, extras = choose_test_projects(available, preferred, 100, 13)
    assert len(selected) == len(set(selected)) == 100
    assert {'owner/repo1', 'owner/repo2'} <= set(selected)
    assert 'owner/missing' not in selected
    assert len(extras) == 98
    assert (selected, extras) == choose_test_projects(reversed(available), reversed(preferred), 100, 13)
    with pytest.raises(ValueError, match='cannot select'):
        choose_test_projects(['owner/one'], preferred, 100, 13)


def test_case_insensitive_holdout_and_duplicate_list(tmp_path):
    assert assign_projects(['Owner/Held'], ['owner/held'], 13, .1) == {'Owner/Held': 'test'}
    path = tmp_path / 'projects.txt'
    path.write_text('owner/repo\nOwner/Repo\n')
    with pytest.raises(ValueError, match='Duplicate'):
        load_test_projects(path)


def test_resplit_preserves_samples_and_updates_counts(tmp_path):
    output = tmp_path / 'output'
    metadata = tmp_path / 'build' / 'metadata'
    output.mkdir()
    metadata.mkdir(parents=True)
    projects = [f'owner/repo{i}' for i in range(300)]
    rows = [{'id': str(i), 'project': p, 'split': 'test', 'label': 'Thing', 'input': 'unchanged'} for i, p in enumerate(projects)]
    for split in ('train', 'validation', 'test'):
        part = rows if split == 'test' else []
        (output / f'{split}.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in part), encoding='utf-8')
        (metadata / f'{split}.json').write_text(json.dumps([{'file': f"repos/{r['project']}/a.py"} for r in part]))
    (metadata / 'split_manifest.json').write_text('{"split_profile":"paper_project"}')
    (output / 'preprocess_stats.json').write_text(json.dumps({'written': 300, 'input_records': 302, 'dropped_incomplete': 2, 'test_written': 300}))
    preferred = tmp_path / 'preferred.txt'
    preferred.write_text('owner/repo0\nowner/missing\n')
    audit = resplit_completed_dataset(metadata.parent, output, preferred, 100, 13, .1, project_from_row)
    assert audit['written_projects']['test'] == 100
    assert audit['retained_preferred_projects'] == ['owner/repo0']
    assert audit['unavailable_preferred_projects'] == ['owner/missing']
    assert len(audit['supplemented_projects']) == 99
    final_rows = list(iter_output_rows(output))
    assert sorted(({k:v for k,v in r.items() if k != 'split'} for r in final_rows), key=lambda r:r['id']) == sorted(({k:v for k,v in r.items() if k != 'split'} for r in rows), key=lambda r:r['id'])
    sets = {s: {r['project'] for r in final_rows if r['split'] == s} for s in ('train', 'validation', 'test')}
    assert sets['train'] and sets['validation']
    assert not (sets['train'] & sets['test'] or sets['validation'] & sets['test'] or sets['train'] & sets['validation'])
    stats = json.loads((output / 'preprocess_stats.json').read_text())
    assert stats['dropped_incomplete'] == 2
    assert sum(stats[f'{s}_written'] for s in sets) == 300
    assert stats['test_written'] == 100
    assert len((output / 'test_projects.txt').read_text().splitlines()) == 100
