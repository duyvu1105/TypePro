"""Render isolated graph experiment jobs; no implicit main revision resolution."""
from collections import Counter
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parent
REPO_ROOT=ROOT.parent
BRANCH='experiment/graph-context-v1'
PREFIX='typepro-graph-v1'


def validate_profile(profile):
    if profile.get('schema_version')!='typepro-graph-experiment-profile-v1' or profile.get('branch')!=BRANCH:
        raise ValueError('Require explicit graph experiment profile/branch')
    revision=profile.get('revision','')
    if not re.fullmatch('[0-9a-f]{40}',revision):
        raise ValueError('Graph experiment requires a checked full SHA; latest/main are not accepted')
    for command in (['git','merge-base','--is-ancestor',revision,'refs/heads/'+BRANCH],
                    ['git','cat-file','-e',revision+':typepro/analysis/graph_context.py']):
        subprocess.run(command,cwd=REPO_ROOT,check=True,capture_output=True)
    dataset=profile.get('input_dataset','')
    if not re.fullmatch(r'[A-Za-z0-9_-]+/[a-z0-9-]+',dataset):
        raise ValueError('Profile requires an explicit frozen graph input Dataset')
    if not re.fullmatch('[0-9a-f]{64}',profile.get('input_manifest_sha256','')):
        raise ValueError('Profile requires a SHA256-locked input manifest')
    if profile.get('input_public') is not True and not {'duyvu1105','duymign','vdduy1105'}<=set(profile.get('input_readable_accounts',[])):
        raise ValueError('Frozen graph inputs must be public or explicitly shared with all three runner accounts')
    return revision


def isolated_plan(account_plan):
    result=[]
    for item in account_plan['merge_datasets']:
        owner=item['dataset_id'].split('/')[0]
        index,count=item['shard_index'],item['shard_count']
        suffix=f'{index:02d}-of-{count:02d}'
        result.append(dict(account=owner,kernel=f'{owner}/{PREFIX}-{suffix}',
                           dataset=f'{owner}/{PREFIX}-data-{suffix}',
                           public=item['public_dataset'],shard_index=index,shard_count=count,
                           logical_shard_index=item['logical_shard_index'],status='pending'))
    if len(result)!=21 or Counter(r['account'] for r in result)!=Counter({'duyvu1105':7,'duymign':7,'vdduy1105':7}):
        raise ValueError('Graph profile must preserve all 21 coordinates, 7 per account')
    if len({(r['shard_index'],r['shard_count']) for r in result})!=21:
        raise ValueError('Duplicate graph physical coordinates')
    return result


def graph_notebook(profile,job):
    from generate_notebooks import notebook, code, markdown, pinned_checkout_source
    setup='''import json, os, subprocess, sys
from pathlib import Path

def run(command):
    subprocess.run([str(v) for v in command],check=True)

REPO_DIR=Path('/kaggle/working/TypePro')
run([sys.executable,'-m','pip','install','-q','transformers','torch','kaggle==1.7.4.2'])
run(['git','clone','--no-checkout','https://github.com/duyvu1105/TypePro.git',REPO_DIR])
'''+pinned_checkout_source(profile['revision'])+'''
sys.path.insert(0,str(REPO_DIR))
'''
    config='PROFILE='+repr(profile)+'\nJOB='+repr(job)+'\n'
    execute='''from typepro.data.graph_dataset import freeze_roster, export_graph_dataset, sha256
from typepro.data.prepare import stable_number
from transformers import AutoTokenizer

INPUT=Path('/kaggle/input')/PROFILE['input_dataset'].split('/')[1]
if sha256(INPUT/'input_manifest.json')!=PROFILE['input_manifest_sha256']:
    raise RuntimeError('Frozen graph input manifest mismatch')
locks=json.loads((INPUT/'input_manifest.json').read_text())
for name,expected in locks['files'].items():
    path=INPUT/name
    if not path.resolve().is_relative_to(INPUT.resolve()) or sha256(path)!=expected:
        raise RuntimeError('Frozen input file mismatch: '+name)
roster,labels=freeze_roster(INPUT/'baseline')
roster=[r for r in roster if stable_number(r['target']['project'],17)%JOB['shard_count']==JOB['shard_index']]
source_locks=json.loads((INPUT/'source_locks.json').read_text())
dependency_locks=json.loads((INPUT/'dependency_locks.json').read_text())
tokenizer=AutoTokenizer.from_pretrained(INPUT/'tokenizer',local_files_only=True)
OUTPUT=Path('/kaggle/working/graph-context-v1')
manifest=export_graph_dataset(roster,labels,Path('/kaggle/working/graph-sources'),source_locks,
    dependency_locks,tokenizer,OUTPUT,dependency_root=INPUT/'baseline',clone_missing=True,partition=(JOB['shard_index'],JOB['shard_count']))
print({'outcomes':manifest['outcomes'],'targets':manifest['total_targets'],'revision':PROFILE['revision']})
'''
    publish='''from typepro.publishing.graph import publish_graph_dataset
from kaggle_secrets import UserSecretsClient
secrets=UserSecretsClient()
username=secrets.get_secret('TYPEPRO_PUBLISH_USERNAME')
key=secrets.get_secret('TYPEPRO_PUBLISH_KEY')
if username!=JOB['account']:
    raise RuntimeError('Publisher credential username mismatch')
os.environ['KAGGLE_USERNAME']=username
os.environ['KAGGLE_KEY']=key
os.environ.pop('KAGGLE_API_TOKEN',None)
publish_graph_dataset(OUTPUT,JOB['dataset'],public=JOB['public'])
'''
    return notebook([markdown('# TypePro graph-context-v1 experiment\nFrozen inputs, exact source revision, separate experiment output.'),
                     code(config),code(setup),code(execute),code(publish)])


def render_profile(profile_path,state_parent,requested_revision=None):
    profile=json.loads(Path(profile_path).read_text())
    revision=validate_profile(profile)
    if requested_revision and requested_revision!=revision:
        raise ValueError('Scheduler revision differs from graph profile')
    jobs=isolated_plan(json.loads((ROOT/'shard_account_plan.json').read_text()))
    for job in jobs:
        directory=Path(state_parent)/'graph-context-v1'/job['account']/f"{job['shard_index']:02d}-of-{job['shard_count']}"
        directory.mkdir(parents=True,exist_ok=True)
        rendered=graph_notebook(profile,job)
        (directory/'graph.ipynb').write_text(json.dumps(rendered,indent=1))
        metadata=dict(id=job['kernel'],title=job['kernel'].split('/')[1],code_file='graph.ipynb',
                      language='python',kernel_type='notebook',is_private=True,enable_gpu=False,
                      enable_internet=True,dataset_sources=[profile['input_dataset']],kernel_sources=[],competition_sources=[])
        (directory/'kernel-metadata.json').write_text(json.dumps(metadata,indent=2))
        job['payload']=str(directory)
    plan=dict(schema_version='typepro-graph-experiment-plan-v1',revision=revision,
              profile=profile, jobs=jobs,max_active_per_account=5,
              final_dataset='duyvu1105/typepro-graph-v1-final',final_public=False,
              merge_datasets=[j['dataset'] for j in jobs])
    (Path(state_parent)/'graph-context-v1'/'plan.json').write_text(json.dumps(plan,indent=2))
    merge = graph_merge_notebook(profile,plan)
    merge_dir=Path(state_parent)/'graph-context-v1'/'merge'
    merge_dir.mkdir(parents=True,exist_ok=True)
    (merge_dir/'merge.ipynb').write_text(json.dumps(merge,indent=1))
    (merge_dir/'kernel-metadata.json').write_text(json.dumps(dict(id='duyvu1105/typepro-graph-v1-merge',
        title='typepro-graph-v1-merge',code_file='merge.ipynb',language='python',kernel_type='notebook',
        is_private=True,enable_gpu=False,enable_internet=True,
        dataset_sources=[profile['input_dataset'],*plan['merge_datasets']],kernel_sources=[],competition_sources=[]),indent=2))
    return plan


def graph_merge_notebook(profile,plan):
    from generate_notebooks import notebook,code,markdown,pinned_checkout_source
    setup="""import json, os, subprocess, sys, zipfile
from pathlib import Path

def run(command):
    subprocess.run([str(v) for v in command],check=True)
REPO_DIR=Path('/kaggle/working/TypePro')
run([sys.executable,'-m','pip','install','-q','torch','kaggle==1.7.4.2'])
run(['git','clone','--no-checkout','https://github.com/duyvu1105/TypePro.git',REPO_DIR])
"""+pinned_checkout_source(profile['revision'])+"\nsys.path.insert(0,str(REPO_DIR))\n"
    execute="""from typepro.data.graph_dataset import freeze_roster, merge_graph_datasets, verify_graph_dataset, sha256
PROFILE=PROFILE_VALUE
PLAN=PLAN_VALUE
INPUT=Path('/kaggle/input')/PROFILE['input_dataset'].split('/')[1]
if sha256(INPUT/'input_manifest.json')!=PROFILE['input_manifest_sha256']:
    raise RuntimeError('Graph input manifest mismatch')
roster,_=freeze_roster(INPUT/'baseline')
roots=[]
for job in PLAN['jobs']:
    archive=Path('/kaggle/input')/job['dataset'].split('/')[1]/'graph-dataset.zip'
    root=Path('/kaggle/working/merge-inputs')/job['dataset'].split('/')[1]
    root.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        seen=set()
        for member in bundle.infolist():
            path=root/member.filename
            if not path.resolve().is_relative_to(root.resolve()) or member.filename.casefold() in seen:
                raise RuntimeError('Unsafe graph archive path or collision')
            if (member.external_attr>>16)&0o170000==0o120000:
                raise RuntimeError('Symlink in graph archive')
            seen.add(member.filename.casefold())
        bundle.extractall(root)
    manifest=verify_graph_dataset(root)
    if manifest.get('partition')!={'shard_index':job['shard_index'],'shard_count':job['shard_count']}:
        raise RuntimeError('Graph Dataset physical coordinate mismatch')
    roots.append(root)
OUTPUT=Path('/kaggle/working/graph-v1-final')
merge_graph_datasets(roots,OUTPUT,roster)
""".replace('PROFILE_VALUE',repr(profile)).replace('PLAN_VALUE',repr(plan))
    publish="""from typepro.publishing.graph import publish_graph_dataset
from kaggle_secrets import UserSecretsClient
secrets=UserSecretsClient()
username=secrets.get_secret('TYPEPRO_FINAL_USERNAME')
key=secrets.get_secret('TYPEPRO_FINAL_KEY')
if username!='duyvu1105':
    raise RuntimeError('Final graph publisher must be duyvu1105')
os.environ['KAGGLE_USERNAME']=username
os.environ['KAGGLE_KEY']=key
os.environ.pop('KAGGLE_API_TOKEN',None)
publish_graph_dataset(OUTPUT,'duyvu1105/typepro-graph-v1-final',public=False)
"""
    return notebook([markdown('# Merge exactly 21 graph experiment partitions'),code(setup),code(execute),code(publish)])
