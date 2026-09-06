import json
import subprocess
import sys
from pathlib import Path

import pytest

from fixed_test_split import assign_projects, choose_test_projects, load_test_projects, prepare_project_holdout, iter_output_rows
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


def test_preflight_and_writer_share_filter_and_write_only_one_copy(tmp_path):
    output = tmp_path / 'output'
    build = tmp_path / 'build'
    metadata = build / 'metadata'
    raw = build / 'raw_slices'
    metadata.mkdir(parents=True)
    raw.mkdir()
    projects = [f'owner/repo{i}' for i in range(300)]
    rows = [{'id': str(i), 'file': f'repos/{p}/a.py', 'split': 'test', 'name': 'x',
             'scope': 'arg', 'gttype': 'Thing', 'interprocedural_slice': 'def f(x): pass',
             'recommendation_types': [{'name': 'Thing', 'definition': 'class Thing: pass'}]}
            for i, p in enumerate(projects)]
    rows.append({**rows[0], 'file': 'repos/owner/empty/a.py', 'recommendation_types': []})
    (raw / 'rows.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    for split in ('train', 'validation', 'test'):
        (metadata / f'{split}.json').write_text(json.dumps(rows if split == 'test' else []))
    (metadata / 'split_manifest.json').write_text('{"split_profile":"paper_project"}')
    preferred = tmp_path / 'preferred.txt'
    preferred.write_text('owner/repo0\nowner/missing\nowner/empty\n')
    audit = prepare_project_holdout(build, output, preferred, 100, 13, .1, project_from_row)
    assert not list(output.glob('*.jsonl*')), 'Preflight must never copy the processed dataset'
    assert audit['written_projects']['test'] == 100
    assert audit['retained_preferred_projects'] == ['owner/repo0']
    assert set(audit['unavailable_preferred_projects']) == {'owner/missing', 'owner/empty'}
    assert len(audit['supplemented_projects']) == 99
    script = Path(__file__).resolve().parents[1] / 'preprocess_generative.py'
    subprocess.run([sys.executable, str(script), '--input', str(raw), '--output-dir', str(output),
                    '--project-split-map', str(output / 'project_split_map.json')], check=True, capture_output=True)
    final_rows = list(iter_output_rows(output))
    assert len(final_rows) == 300
    assert {r['id'] for r in final_rows} == {str(i) for i in range(300)}
    assert all(r['label'] == 'Thing' and r['interprocedural_slice'] == 'def f(x): pass' for r in final_rows)
    sets = {s: {r['project'] for r in final_rows if r['split'] == s} for s in ('train', 'validation', 'test')}
    assert sets['train'] and sets['validation'] and len(sets['test']) == 100
    assert not (sets['train'] & sets['test'] or sets['validation'] & sets['test'] or sets['train'] & sets['validation'])
    stats = json.loads((output / 'preprocess_stats.json').read_text())
    assert stats['dropped_incomplete'] == 1
    assert all(stats[f'{s}_written'] == audit['expected_written_counts'][s] for s in sets)
    assert not list(output.glob('*.tmp'))
    assert len((output / 'test_projects.txt').read_text().splitlines()) == 100
