import ast
from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'kaggle_notebooks'))
import graph_profile
from typepro.audit.graph_comparison import compare


def profile():
    return dict(schema_version='typepro-graph-experiment-profile-v1',branch=graph_profile.BRANCH,
                revision='a'*40,input_dataset='owner/frozen-inputs',input_manifest_sha256='b'*64,input_public=True)


def test_profile_preserves_21_coordinates_visibility_and_separate_slugs():
    production=json.loads((ROOT/'kaggle_notebooks/shard_account_plan.json').read_text())
    jobs=graph_profile.isolated_plan(production)
    assert {(j['shard_index'],j['shard_count']) for j in jobs}=={(j['shard_index'],j['shard_count']) for j in production['merge_datasets']}
    assert Counter(j['account'] for j in jobs)=={'duyvu1105':7,'duymign':7,'vdduy1105':7}
    assert all(j['dataset'] not in {r['dataset_id'] for r in production['merge_datasets']} for j in jobs)
    assert all(j['public']==(j['account']!='duyvu1105') for j in jobs)


def test_generated_graph_and_merge_notebooks_compile_and_merge_exact_inputs():
    production=json.loads((ROOT/'kaggle_notebooks/shard_account_plan.json').read_text())
    jobs=graph_profile.isolated_plan(production)
    plan=dict(jobs=jobs,merge_datasets=[j['dataset'] for j in jobs])
    for nb in [graph_profile.graph_notebook(profile(),jobs[0]),graph_profile.graph_merge_notebook(profile(),plan)]:
        for cell in nb['cells']:
            if cell['cell_type']=='code':
                ast.parse(cell['source'])
    merge='\n'.join(c['source'] for c in graph_profile.graph_merge_notebook(profile(),plan)['cells'])
    assert 'physical coordinate mismatch' in merge
    assert 'typepro-graph-v1-final' in merge
    assert 'public=False' in merge


def test_profile_rejects_main_and_unlocked_inputs_before_git_access():
    bad=profile(); bad['revision']='latest'
    with pytest.raises(ValueError,match='checked full SHA'):
        graph_profile.validate_profile(bad)
    bad=profile(); bad['branch']='main'
    with pytest.raises(ValueError,match='explicit graph'):
        graph_profile.validate_profile(bad)


def test_project_bootstrap_counts_failed_targets_as_incorrect():
    ledger=[dict(target_id='1',id='a',target=dict(project='p1',scope='return'),outcome='ready',label='int',audit={'prompt_tokens':100}),
            dict(target_id='2',id='b',target=dict(project='p2',scope='arg'),outcome='budget_exceeded',label='str')]
    baseline=[dict(id='a',prediction='str'),dict(id='b',prediction='str')]
    graph=[dict(id='a',prediction='int'),dict(id='b',prediction='str')]
    report=compare(ledger,baseline,graph,bootstrap_samples=100)
    assert report['end_to_end']==dict(targets=2,baseline_em=.5,graph_em=.5,fixes=1,regressions=1)
    assert report['common_ready']['targets']==1
    assert report['outcomes']['budget_exceeded']==1
    assert report==compare(ledger,baseline,graph,bootstrap_samples=100)
