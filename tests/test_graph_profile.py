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


def test_input_freezer_pins_baseline_and_checks_all_source_payloads(tmp_path):
    spec=dict(baseline_dataset='owner/baseline/24',baseline_manifest_sha256='a'*64,projects=['owner/repo'])
    path=tmp_path/'spec.json';path.write_text(json.dumps(spec))
    metadata=graph_profile.render_input_freezer(path,tmp_path/'render')
    assert metadata['dataset_sources']==['owner/baseline/24']
    assert metadata['is_private'] and not metadata['enable_gpu']
    nb=json.loads((tmp_path/'render/freeze.ipynb').read_text())
    source=nb['cells'][1]['source']
    ast.parse(source)
    assert "sha256(root/'manifest.json')" in source
    assert "sha256(root/record['file'])" in source
    assert 'dependency_locks.json' in source
    spec['baseline_dataset']='owner/baseline';path.write_text(json.dumps(spec))
    with pytest.raises(ValueError,match='exact baseline'):
        graph_profile.render_input_freezer(path,tmp_path/'bad')


def test_graph_source_bundle_and_versioned_dependency_mounts():
    p=profile();p['dependency_dataset']='owner/baseline/24'
    production=json.loads((ROOT/'kaggle_notebooks/shard_account_plan.json').read_text())
    jobs=graph_profile.isolated_plan(production)
    for nb in [graph_profile.graph_notebook(p,jobs[0],b'fixture bundle'),
               graph_profile.graph_merge_notebook(p,dict(jobs=jobs),b'fixture bundle')]:
        cells=[c['source'] for c in nb['cells'] if c['cell_type']=='code']
        for source in cells:ast.parse(source)
        assert any('Source bundle checksum mismatch' in source for source in cells)
    source='\n'.join(c['source'] for c in graph_profile.graph_notebook(p,jobs[0])['cells'])
    assert 'dependency_index=dependency_index' in source
    assert 'Frozen dependency Dataset version mismatch' in source


def test_freezer_accepts_only_v24_identical_objects_on_a_newer_mount(tmp_path):
    import base64
    import hashlib
    mount=tmp_path/'input/slug';mount.mkdir(parents=True)
    kb=mount/'project_kb/owner__repo/knowledge_base.json';kb.parent.mkdir(parents=True)
    kb.write_text(json.dumps({'schema_version':'typepro-project-kb-v7-source-evidence','records':[]}))
    (mount/'manifest.json').write_text('{}')
    (mount/'project_kb_index.json').write_text(json.dumps({'owner__repo':kb.relative_to(mount).as_posix()}))
    spec=dict(baseline_dataset='owner/slug/24',baseline_manifest_sha256='a'*64,projects=['owner/repo'],
        kb_checksums={'owner/repo':dict(path=kb.relative_to(mount).as_posix(),bytes=kb.stat().st_size,
            md5=base64.b64encode(hashlib.md5(kb.read_bytes()).digest()).decode())})
    path=tmp_path/'spec.json';path.write_text(json.dumps(spec))
    graph_profile.render_input_freezer(path,tmp_path/'render')
    nb=json.loads((tmp_path/'render/freeze.ipynb').read_text())
    source=nb['cells'][1]['source'].replace('/kaggle/input',str(tmp_path/'input')).replace('/kaggle/working',str(tmp_path/'working'))
    (tmp_path/'working').mkdir()
    exec(compile(source,'freezer','exec'),{})
    locks=json.loads((tmp_path/'working/frozen-locks/dependency_locks.json').read_text())
    assert locks=={'owner/repo':hashlib.sha256(kb.read_bytes()).hexdigest()}
    provenance=json.loads((tmp_path/'working/frozen-locks/freeze_provenance.json').read_text())
    assert provenance['dependency_mount_manifest_sha256']==hashlib.sha256(b'{}').hexdigest()
    kb.write_bytes(kb.read_bytes().replace(b'[]',b'{}'))
    with pytest.raises(RuntimeError,match='checksum differs from v24'):
        exec(compile(source,'freezer','exec'),{})


def test_reuse_existing_shards_preserves_kernels_coordinates_auth_and_graph_outputs():
    production=json.loads((ROOT/'kaggle_notebooks/shard_account_plan.json').read_text())
    jobs=graph_profile.isolated_plan(production,reuse_shard_notebooks=True)
    assert len(jobs)==21
    assert len({j['kernel'] for j in jobs})==21
    assert all('/typepro-python-shard-' in j['kernel'] for j in jobs)
    assert all('/typepro-graph-v1-data-' in j['dataset'] for j in jobs)
    p=dict(profile(),reuse_shard_notebooks=True,direct_dataset='owner/baseline/26',
        dataset_manifest_sha256='c'*64,tokenizer_fingerprint='d'*64,
        source_locks={'owner/repo':'a'*40},dependency_locks={'owner/repo':'b'*64},
        dependency_index={'owner__repo':'project_kb/owner__repo/knowledge_base.json'},
        tokenizer_repository='Qwen/Qwen2.5-Coder-0.5B-Instruct',tokenizer_revision='e'*40)
    for job in jobs:
        nb=graph_profile.graph_notebook(p,job,b'fixture bundle')
        source='\n'.join(c['source'] for c in nb['cells'])
        for c in nb['cells']:
            if c['cell_type']=='code':ast.parse(c['source'])
        config=next(c['source'] for c in nb['cells'] if 'ASSIGNED_SHARDS =' in c['source'])
        assert f"SHARD_INDEX = {job['shard_index']}\n" in config
        assert f"SHARD_COUNT = {job['shard_count']}\n" in config
        assert 'TYPEPRO_KAGGLE_IDENTITY=' in source
        assert 'requirements' in source and 'build.txt' in source
        assert 'export_graph_dataset(' in source
        assert 'input_manifest.json' not in source
        assert '--stage' not in source and '--build-import-kb' not in source
        assert nb['metadata']['typepro']['reused_template']==job['template']
    nb=graph_profile.graph_merge_notebook(p,dict(jobs=jobs))
    for c in nb['cells']:
        if c['cell_type']=='code':ast.parse(c['source'])
    source='\n'.join(c['source'] for c in nb['cells'])
    assert "freeze_roster(INPUT)" in source and 'input_manifest.json' not in source
    assert "dataset_root/'manifest.json'" in source and 'root=dataset_root' in source
    neutral = dict(p, model_neutral=True)
    neutral.pop('tokenizer_fingerprint')
    for key in ('tokenizer_repository', 'tokenizer_revision'):
        neutral.pop(key)
    nb = graph_profile.graph_notebook(neutral, jobs[0], b'fixture bundle')
    source = '\n'.join(c['source'] for c in nb['cells'])
    assert 'tokenizer=None' in source
    assert 'AutoTokenizer.from_pretrained' not in source
    assert 'Qwen/' not in source
    for cell in nb['cells']:
        if cell['cell_type'] == 'code':
            ast.parse(cell['source'])
