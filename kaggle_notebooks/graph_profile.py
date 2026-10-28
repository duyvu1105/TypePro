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


def pinned_graph_execution(config_source, execute_source, *, verify_output=True):
    """Run graph construction under a verified interpreter, independent of host."""
    worker = '''import json, sys
from pathlib import Path
if sys.version_info[:3] != (3, 12, 12):
    raise RuntimeError('Graph worker requires Python 3.12.12: '+sys.version)
print({'graph_python':sys.version,'executable':sys.executable},flush=True)
'''+config_source+'''
sys.path.insert(0,str(REPO_DIR))
'''+execute_source
    source = '''# The notebook host may run Python 3.13. Graph ASTs must use 3.12.
import json, os, shutil, subprocess, sys
from pathlib import Path
run([sys.executable,'-m','pip','install','-q','uv==0.9.5'])
graph_uv=shutil.which('uv')
if not graph_uv:
    raise RuntimeError('uv executable missing')
graph_env=os.environ.copy()
graph_env['UV_PYTHON_INSTALL_DIR']='/kaggle/working/graph-python'
subprocess.run([graph_uv,'python','install','3.12.12'],env=graph_env,check=True)
graph_venv=Path('/kaggle/working/graph-python312-venv')
subprocess.run([graph_uv,'venv','--python','3.12.12',str(graph_venv)],env=graph_env,check=True)
graph_python=graph_venv/'bin'/'python'
graph_version=json.loads(subprocess.check_output(
    [str(graph_python),'-c','import sys,json; print(json.dumps(list(sys.version_info[:3])))'],text=True))
if graph_version != [3,12,12]:
    raise RuntimeError('Unexpected graph Python: '+repr(graph_version))
print({'graph_python_verified':graph_version,'executable':str(graph_python)},flush=True)
subprocess.run([graph_uv,'pip','install','--python',str(graph_python),
    '-r',str(REPO_DIR/'requirements'/'build.txt'),
    'transformers==4.57.6','tokenizers==0.22.2','loguru==0.7.3'],env=graph_env,check=True)
# Graph imports use torch utilities, but graph creation needs no CUDA wheels.
subprocess.run([graph_uv,'pip','install','--python',str(graph_python),
    '--index-url','https://download.pytorch.org/whl/cpu','torch==2.9.0'],env=graph_env,check=True)
graph_worker=Path('/kaggle/working/graph_worker.py')
graph_worker.write_text('''+repr(worker)+''',encoding='utf-8')
subprocess.run([str(graph_python),str(graph_worker)],env=graph_env,check=True)
'''
    if verify_output:
        source += '''
OUTPUT=Path('/kaggle/working/graph-context-v1')
graph_manifest=json.loads((OUTPUT/'manifest.json').read_text())
if graph_manifest.get('python_version') != [3,12]:
    raise RuntimeError('Graph manifest Python version mismatch')
'''
    return source


def mounted_dataset_source():
    return '''
def mounted_dataset(reference,marker):
    owner,slug=reference.split('/')[:2]
    base=Path('/kaggle/input')
    candidates=[base/slug,base/'datasets'/owner/slug,base/owner/slug]
    matches=[p for p in candidates if p.is_dir() and (marker is None or (p/marker).is_file())]
    if not matches:
        matches=([p for p in base.rglob(slug) if p.is_dir()] if marker is None else
                 [p.parent for p in base.rglob(marker) if p.parent.name==slug])
    matches=list({p.resolve():p for p in matches}.values())
    if len(matches)!=1:
        raise RuntimeError('Cannot locate unique Dataset mount: '+reference+'; input roots: '+str(list(base.iterdir())))
    return matches[0]
'''


def graph_auth_source(expected_expression,final=False):
    prefix='TYPEPRO_FINAL' if final else 'TYPEPRO_PUBLISH'
    return 'EXPECTED_OWNER='+expected_expression+'\nSECRET_PREFIX='+repr(prefix)+'\n'+'''
from kaggle_secrets import UserSecretsClient
secrets=UserSecretsClient()
def optional_secret(name):
    try:
        return secrets.get_secret(name) or None
    except Exception:
        return None
username=optional_secret(SECRET_PREFIX+'_USERNAME')
key=optional_secret(SECRET_PREFIX+'_KEY')
if bool(username)!=bool(key):
    raise RuntimeError('Publisher Secrets require a complete username/key pair')
if username is None:
    username=optional_secret('KAGGLE_USERNAME')
    key=optional_secret('KAGGLE_KEY')
    if bool(username)!=bool(key):
        raise RuntimeError('Legacy publisher Secrets require a complete pair')
if username is not None and username.casefold()!=EXPECTED_OWNER.casefold():
    raise RuntimeError('Publisher credential username mismatch')
if key:
    auth_dir=Path('/kaggle/working/graph-publish-auth')
    auth_dir.mkdir(exist_ok=True)
    os.environ['KAGGLE_CONFIG_DIR']=str(auth_dir)
    os.environ['KAGGLE_KEY']=key
    os.environ.pop('KAGGLE_API_TOKEN',None)
os.environ['KAGGLE_USERNAME']=EXPECTED_OWNER
print({'publish_owner':EXPECTED_OWNER,'authentication':'explicit Secret' if key else 'Kaggle notebook host'})
'''


def render_input_freezer(spec_path, output):
    """Hash immutable v24 KBs in-place on Kaggle; never rebuild dependencies."""
    from generate_notebooks import notebook, code, markdown
    spec=json.loads(Path(spec_path).read_text())
    if not re.fullmatch(r'[A-Za-z0-9_-]+/[a-z0-9-]+/[1-9][0-9]*',spec['baseline_dataset']):
        raise ValueError('Input freezer requires an exact baseline Dataset version')
    source='SPEC='+repr(spec)+'\n'+'''import base64, hashlib, json
from pathlib import Path

def sha256(path):
    value=hashlib.sha256()
    with path.open('rb') as handle:
        while block:=handle.read(1024*1024):
            value.update(block)
    return value.hexdigest()

root=mounted_dataset(SPEC['baseline_dataset'],'manifest.json')
mount_hash=sha256(root/'manifest.json')
if mount_hash!=SPEC['baseline_manifest_sha256'] and not SPEC.get('kb_checksums'):
    raise RuntimeError('Attached Dataset is not the frozen v24 baseline')
manifest=json.loads((root/'manifest.json').read_text())
if mount_hash==SPEC['baseline_manifest_sha256']:
    for split in ('train','validation','test'):
        record=manifest['output'][split]
        if sha256(root/record['file'])!=record['sha256']:
            raise RuntimeError('Frozen baseline split mismatch: '+split)
original_index=json.loads((root/'project_kb_index.json').read_text())
index={}
locks={}
for number,project in enumerate(SPEC['projects'],1):
    key=project.replace('/','__')
    matches=[k for k in original_index if k.casefold()==key.casefold()]
    if key not in original_index and len(matches)!=1:
        raise RuntimeError('Missing or ambiguous baseline KB identity: '+project)
    relative=original_index[key if key in original_index else matches[0]]
    candidates=[root/relative]
    # Final publisher historically uploaded project_kb under this ZIP stem.
    if relative.startswith('project_kb/'):
        candidates.append(root/'typepro.analysis.project_kb'/relative.removeprefix('project_kb/'))
    matches=[p for p in candidates if p.is_file() and p.resolve().is_relative_to(root.resolve())]
    if len(matches)!=1:
        raise RuntimeError('Missing or ambiguous frozen KB: '+project)
    path=matches[0]
    if SPEC.get('kb_checksums'):
        record=SPEC['kb_checksums'][project]
        if path.relative_to(root).as_posix()!=record['path'] or path.stat().st_size!=record['bytes']:
            raise RuntimeError('Mounted KB differs from exact v24 object: '+project)
        md5=hashlib.md5()
        with path.open('rb') as handle:
            while block:=handle.read(1024*1024):
                md5.update(block)
        if base64.b64encode(md5.digest()).decode()!=record['md5']:
            raise RuntimeError('Mounted KB checksum differs from v24: '+project)
    # Inspect one KB at a time, retaining neither records nor annotated indexes.
    kb=json.loads(path.read_text())
    if kb.get('schema_version')!='typepro-project-kb-v7-source-evidence':
        raise RuntimeError('Incompatible frozen KB: '+project)
    del kb
    locks[project]=sha256(path)
    index[key]=path.relative_to(root).as_posix()
    if number%100==0:
        print({'hashed_projects':number,'total':len(SPEC['projects'])},flush=True)
output=Path('/kaggle/working/frozen-locks')
output.mkdir()
SPEC['dependency_mount_manifest_sha256']=mount_hash
for name,value in [('dependency_locks.json',locks),('project_kb_index.json',index),('freeze_provenance.json',SPEC)]:
    (output/name).write_text(json.dumps(value,indent=2)+'\\n')
print({'frozen_projects':len(locks),'baseline_dataset':SPEC['baseline_dataset']})
'''
    source=source.replace("root=mounted_dataset",mounted_dataset_source()+"\nroot=mounted_dataset",1)
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    (output/'freeze.ipynb').write_text(json.dumps(notebook([
        markdown('# Freeze graph inputs from the exact v24 Dataset'),code(source)]),indent=1))
    metadata=dict(id='duyvu1105/typepro-graph-v1-freeze-v24-inputs',title='typepro-graph-v1-freeze-v24-inputs',
        code_file='freeze.ipynb',language='python',kernel_type='notebook',is_private=True,
        enable_gpu=False,enable_internet=False,dataset_sources=[spec['baseline_dataset']],
        kernel_sources=[],competition_sources=[])
    (output/'kernel-metadata.json').write_text(json.dumps(metadata,indent=2))
    return metadata


def validate_profile(profile):
    branch = profile.get('branch', '')
    if profile.get('schema_version')!='typepro-graph-experiment-profile-v1' or not branch or branch=='main':
        raise ValueError('Require explicit graph experiment profile/branch')
    revision=profile.get('revision','')
    if not re.fullmatch('[0-9a-f]{40}',revision):
        raise ValueError('Graph experiment requires a checked full SHA; latest/main are not accepted')
    subprocess.run(['git', 'check-ref-format', '--branch', branch], cwd=REPO_ROOT, check=True, capture_output=True)
    for command in (['git','merge-base','--is-ancestor',revision,'refs/heads/'+branch],
                    ['git','cat-file','-e',revision+':typepro/analysis/graph_context.py']):
        subprocess.run(command,cwd=REPO_ROOT,check=True,capture_output=True)
    if profile.get('reuse_shard_notebooks'):
        if not re.fullmatch(r'[A-Za-z0-9_-]+/[a-z0-9-]+/[1-9][0-9]*',profile.get('direct_dataset','')):
            raise ValueError('Direct graph inputs require an exact Dataset version')
        for name in (('dataset_manifest_sha256',) if profile.get('model_neutral') else ('dataset_manifest_sha256','tokenizer_fingerprint')):
            if not re.fullmatch('[0-9a-f]{64}',profile.get(name,'')):
                raise ValueError('Direct graph inputs require '+name)
        source=profile.get('source_locks',{})
        dependencies=profile.get('dependency_locks',{})
        if not source or source.keys()!=dependencies.keys():
            raise ValueError('Direct source/dependency locks must cover the same projects')
        if any(not re.fullmatch('[0-9a-f]{40}',v) for v in source.values()) or any(
                not re.fullmatch('[0-9a-f]{64}',v) for v in dependencies.values()):
            raise ValueError('Malformed direct project locks')
        return revision
    dataset=profile.get('input_dataset','')
    if not re.fullmatch(r'[A-Za-z0-9_-]+/[a-z0-9-]+',dataset):
        raise ValueError('Profile requires an explicit frozen graph input Dataset')
    if not re.fullmatch('[0-9a-f]{64}',profile.get('input_manifest_sha256','')):
        raise ValueError('Profile requires a SHA256-locked input manifest')
    if profile.get('dependency_dataset') and not re.fullmatch(r'[A-Za-z0-9_-]+/[a-z0-9-]+/[1-9][0-9]*',profile['dependency_dataset']):
        raise ValueError('Dependency Dataset must pin an exact version')
    if profile.get('input_public') is not True and not {'duyvu1105','duymign','vdduy1105'}<=set(profile.get('input_readable_accounts',[])):
        raise ValueError('Frozen graph inputs must be public or explicitly shared with all three runner accounts')
    return revision


def isolated_plan(account_plan,reuse_shard_notebooks=False):
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
    if reuse_shard_notebooks:
        from commit_shard_versions import load_plan,physical_partitions,plan_for_part,partition_kernel_slug
        _,_,plans=load_plan(ROOT/'shard_account_plan.json')
        templates={}
        for plan in plans:
            for part,coordinate in enumerate(physical_partitions(plan.assigned_shards[0])):
                effective=plan_for_part(plan,part)
                templates[coordinate]=(plan,part,effective)
        for job in result:
            plan,part,effective=templates[(job['shard_index'],job['shard_count'])]
            job.update(kernel=f'{effective.runner_account}/{partition_kernel_slug(effective,part)}',
                       template=plan.notebook_path.name,part_index=part)
            job['dataset']=f"{effective.dataset_owner}/typepro-graph-v1-data-{job['shard_index']:02d}-of-{job['shard_count']:02d}"
    return result


def reused_shard_notebook(profile,job,source_bundle=None):
    """Keep the established shard's configuration, authentication and setup."""
    from generate_notebooks import notebook,code,markdown,pinned_checkout_source
    from commit_shard_versions import load_plan,render_part_version
    _,_,plans=load_plan(ROOT/'shard_account_plan.json')
    plan=next(p for p in plans if p.notebook_path.name==job['template'])
    old=render_part_version(json.loads(plan.notebook_path.read_text()),plan,job['part_index'])
    boundary=next(i for i,c in enumerate(old['cells']) if '## Optional automatic resume' in c['source'])
    cells=old['cells'][:boundary]
    cells[0]=markdown('# TypePro graph shard\nReuse this shard notebook and the attached Dataset KBs; publish graph outputs separately.')
    config=next(c for c in cells if 'ASSIGNED_SHARDS =' in c['source'])
    config['source']=re.sub(r'^BRANCH = .+$','BRANCH = '+repr(profile['branch']),config['source'],flags=re.MULTILINE)
    config['source']+='\nPROFILE='+repr(profile)+'\nJOB='+repr(job)+'\n'
    setup=next(c for c in cells if '"git", "clone"' in c['source'])
    marker='\nPIPELINE_DIR = '
    if marker not in setup['source']:
        raise ValueError('Existing shard setup has no checkout insertion point')
    setup['source']=setup['source'].replace(marker,pinned_checkout_source(profile['revision'],source_bundle)+marker,1)
    setup['source']+='''
sys.path.insert(0,str(REPO_DIR))
run([sys.executable,'-m','pip','install','-q','transformers==4.57.6','tokenizers==0.22.2','torch','loguru==0.7.3'])
from typepro.analysis.project_index import project_module_aliases
'''
    execute='''from typepro.data.graph_dataset import freeze_roster, export_graph_dataset, sha256
from typepro.data.prepare import stable_number
from typepro.shared.context_packing import tokenizer_fingerprint
from transformers import AutoTokenizer

BASELINE=mounted_dataset(PROFILE['direct_dataset'],'manifest.json')
if sha256(BASELINE/'manifest.json')!=PROFILE['dataset_manifest_sha256']:
    raise RuntimeError('Attached Dataset changed since scheduling')
roster,labels=freeze_roster(BASELINE)
roster=[r for r in roster if stable_number(r['target']['project'],17)%SHARD_COUNT==SHARD_INDEX]
tokenizer=AutoTokenizer.from_pretrained(PROFILE['tokenizer_repository'],revision=PROFILE['tokenizer_revision'])
tokenizer_dir=Path('/kaggle/working/graph-tokenizer')
tokenizer.save_pretrained(tokenizer_dir)
tokenizer=AutoTokenizer.from_pretrained(tokenizer_dir,local_files_only=True)
if tokenizer_fingerprint(tokenizer)!=PROFILE['tokenizer_fingerprint']:
    raise RuntimeError('Frozen tokenizer fingerprint mismatch')
OUTPUT=Path('/kaggle/working/graph-context-v1')
print({'phase':'graph_export','targets':len(roster),'shard_index':SHARD_INDEX,'shard_count':SHARD_COUNT},flush=True)
manifest=export_graph_dataset(roster,labels,Path('/kaggle/working/graph-sources'),
    PROFILE['source_locks'],PROFILE['dependency_locks'],tokenizer,OUTPUT,
    dependency_root=BASELINE,dependency_index=PROFILE['dependency_index'],clone_missing=True,
    partition=(SHARD_INDEX,SHARD_COUNT))
print({'outcomes':manifest['outcomes'],'targets':manifest['total_targets'],'revision':PROFILE['revision']})
'''
    if profile.get('model_neutral'):
        start = execute.index('tokenizer=AutoTokenizer.from_pretrained')
        end = execute.index('OUTPUT=Path', start)
        execute = execute[:start] + 'tokenizer=None\n' + execute[end:]
        execute = execute.replace('from transformers import AutoTokenizer\n', '')
        execute = execute.replace('from typepro.shared.context_packing import tokenizer_fingerprint\n', '')
    cells.extend([markdown('## Build graph context using the attached existing KBs'),
                  code(pinned_graph_execution(config['source'],mounted_dataset_source()+execute)),
                  markdown('## Verify and publish this graph shard'),
                  code("from typepro.publishing.graph import publish_graph_dataset\npublish_graph_dataset(OUTPUT,JOB['dataset'],public=JOB['public'])")])
    result=notebook(cells)
    result['metadata'].update(typepro=dict(old['metadata']['typepro'],context_policy_version='graph-context-v1',
        source_revision=profile['revision'],graph_dataset=job['dataset'],reused_template=job['template']))
    return result


def graph_notebook(profile,job,source_bundle=None):
    if profile.get('reuse_shard_notebooks'):
        return reused_shard_notebook(profile,job,source_bundle)
    from generate_notebooks import notebook, code, markdown, pinned_checkout_source
    setup='''import json, os, subprocess, sys
from pathlib import Path

def run(command):
    subprocess.run([str(v) for v in command],check=True)

REPO_DIR=Path('/kaggle/working/TypePro')
run([sys.executable,'-m','pip','install','-q','transformers==4.57.6','tokenizers==0.22.2','torch','loguru==0.7.3','kaggle==1.7.4.2'])
run(['git','clone','--no-checkout','https://github.com/duyvu1105/TypePro.git',REPO_DIR])
'''+pinned_checkout_source(profile['revision'],source_bundle)+'''
sys.path.insert(0,str(REPO_DIR))
from typepro.analysis.project_index import project_module_aliases
'''
    config='PROFILE='+repr(profile)+'\nJOB='+repr(job)+'\n'
    execute='''from typepro.data.graph_dataset import freeze_roster, export_graph_dataset, sha256
from typepro.data.prepare import stable_number
from transformers import AutoTokenizer

INPUT=mounted_dataset(PROFILE['input_dataset'],'input_manifest.json')
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
from typepro.shared.context_packing import tokenizer_fingerprint
if locks.get('tokenizer_fingerprint') and tokenizer_fingerprint(tokenizer)!=locks['tokenizer_fingerprint']:
    raise RuntimeError('Frozen tokenizer fingerprint mismatch')
dependency_root=INPUT/'baseline'
dependency_index=None
if PROFILE.get('dependency_dataset'):
    dependency_root=mounted_dataset(PROFILE['dependency_dataset'],'manifest.json')
    if sha256(dependency_root/'manifest.json')!=locks.get('dependency_mount_manifest_sha256',locks['baseline_manifest_sha256']):
        raise RuntimeError('Frozen dependency Dataset version mismatch')
    dependency_index=json.loads((INPUT/'project_kb_index.json').read_text())
OUTPUT=Path('/kaggle/working/graph-context-v1')
manifest=export_graph_dataset(roster,labels,Path('/kaggle/working/graph-sources'),source_locks,
    dependency_locks,tokenizer,OUTPUT,dependency_root=dependency_root,dependency_index=dependency_index,
    clone_missing=True,partition=(JOB['shard_index'],JOB['shard_count']))
print({'outcomes':manifest['outcomes'],'targets':manifest['total_targets'],'revision':PROFILE['revision']})
'''
    publish='''from typepro.publishing.graph import publish_graph_dataset
publish_graph_dataset(OUTPUT,JOB['dataset'],public=JOB['public'])
'''
    execute=execute.replace('INPUT=mounted_dataset',mounted_dataset_source()+'\nINPUT=mounted_dataset',1)
    return notebook([markdown('# TypePro graph-context-v1 experiment\nFrozen inputs, exact source revision, separate experiment output.'),
                     code(config),code(setup),code(graph_auth_source("JOB['account']")),code(execute),code(publish)])


def render_profile(profile_path,state_parent,requested_revision=None,source_bundle=None):
    profile=json.loads(Path(profile_path).read_text())
    revision=validate_profile(profile)
    if requested_revision and requested_revision!=revision:
        raise ValueError('Scheduler revision differs from graph profile')
    jobs=isolated_plan(json.loads((ROOT/'shard_account_plan.json').read_text()),profile.get('reuse_shard_notebooks',False))
    for job in jobs:
        directory=Path(state_parent)/'graph-context-v1'/job['account']/f"{job['shard_index']:02d}-of-{job['shard_count']}"
        directory.mkdir(parents=True,exist_ok=True)
        rendered=graph_notebook(profile,job,source_bundle)
        (directory/'graph.ipynb').write_text(json.dumps(rendered,indent=1))
        sources=([profile['direct_dataset']] if profile.get('reuse_shard_notebooks') else
                 [profile['input_dataset']]+([profile['dependency_dataset']] if profile.get('dependency_dataset') else []))
        metadata=dict(id=job['kernel'],title=job['kernel'].split('/')[1],code_file='graph.ipynb',
                      language='python',kernel_type='notebook',is_private=True,enable_gpu=False,
                      enable_internet=True,dataset_sources=sources,kernel_sources=[],competition_sources=[])
        (directory/'kernel-metadata.json').write_text(json.dumps(metadata,indent=2))
        job['payload']=str(directory)
    plan=dict(schema_version='typepro-graph-experiment-plan-v1',revision=revision,
              profile=profile, jobs=jobs,max_active_per_account=5,
              final_dataset='duyvu1105/typepro-graph-v1-final',final_public=False,
              merge_datasets=[j['dataset'] for j in jobs])
    (Path(state_parent)/'graph-context-v1'/'plan.json').write_text(json.dumps(plan,indent=2))
    merge = graph_merge_notebook(profile,plan,source_bundle)
    merge_dir=Path(state_parent)/'graph-context-v1'/'merge'
    merge_dir.mkdir(parents=True,exist_ok=True)
    (merge_dir/'merge.ipynb').write_text(json.dumps(merge,indent=1))
    merge_slug='merge-dataset' if profile.get('reuse_shard_notebooks') else 'typepro-graph-v1-merge'
    (merge_dir/'kernel-metadata.json').write_text(json.dumps(dict(id='duyvu1105/'+merge_slug,
        title=merge_slug,code_file='merge.ipynb',language='python',kernel_type='notebook',
        is_private=True,enable_gpu=False,enable_internet=True,
        dataset_sources=[profile.get('direct_dataset') or profile['input_dataset'],*plan['merge_datasets']],kernel_sources=[],competition_sources=[]),indent=2))
    return plan


def graph_merge_notebook(profile,plan,source_bundle=None):
    from generate_notebooks import notebook,code,markdown,pinned_checkout_source
    setup="""import json, os, subprocess, sys, zipfile
from pathlib import Path

def run(command):
    subprocess.run([str(v) for v in command],check=True)
REPO_DIR=Path('/kaggle/working/TypePro')
run([sys.executable,'-m','pip','install','-q','torch','kaggle==1.7.4.2'])
run(['git','clone','--no-checkout','https://github.com/duyvu1105/TypePro.git',REPO_DIR])
"""+pinned_checkout_source(profile['revision'],source_bundle)+"\nsys.path.insert(0,str(REPO_DIR))\n"
    execute="""from typepro.data.graph_dataset import freeze_roster, merge_graph_datasets, verify_graph_dataset, sha256
PROFILE=PROFILE_VALUE
PLAN=PLAN_VALUE
INPUT=mounted_dataset(PROFILE['input_dataset'],'input_manifest.json')
if sha256(INPUT/'input_manifest.json')!=PROFILE['input_manifest_sha256']:
    raise RuntimeError('Graph input manifest mismatch')
roster,_=freeze_roster(INPUT/'baseline')
roots=[]
for job in PLAN['jobs']:
    dataset_root=mounted_dataset(job['dataset'],None)
    archive=dataset_root/'graph-dataset.zip'
    root=Path('/kaggle/working/merge-inputs')/job['dataset'].split('/')[1]
    root.mkdir(parents=True,exist_ok=True)
    if archive.is_file():
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
    elif (dataset_root/'graph-dataset/manifest.json').is_file():
        root=dataset_root/'graph-dataset'
    elif (dataset_root/'manifest.json').is_file():
        # Kaggle may auto-extract graph-dataset.zip at the mount root.
        root=dataset_root
    else:
        raise RuntimeError('Missing graph archive or extracted Dataset')
    manifest=verify_graph_dataset(root)
    if manifest.get('partition')!={'shard_index':job['shard_index'],'shard_count':job['shard_count']}:
        raise RuntimeError('Graph Dataset physical coordinate mismatch')
    if manifest.get('implementation_sha')!=PROFILE['revision']:
        raise RuntimeError('Graph Dataset implementation commit mismatch')
    roots.append(root)
OUTPUT=Path('/kaggle/working/graph-v1-final')
merge_graph_datasets(roots,OUTPUT,roster)
""".replace('PROFILE_VALUE',repr(profile)).replace('PLAN_VALUE',repr(plan))
    execute=execute.replace('INPUT=mounted_dataset',mounted_dataset_source()+'\nINPUT=mounted_dataset',1)
    if profile.get('reuse_shard_notebooks'):
        start=execute.index("INPUT=mounted_dataset")
        end=execute.index('roots=[]',start)
        execute=execute[:start]+'''INPUT=mounted_dataset(PROFILE['direct_dataset'],'manifest.json')
if sha256(INPUT/'manifest.json')!=PROFILE['dataset_manifest_sha256']:
    raise RuntimeError('Attached Dataset changed since scheduling')
roster,_=freeze_roster(INPUT)
'''+execute[end:]
    publish="""from typepro.publishing.graph import publish_graph_dataset
publish_graph_dataset(OUTPUT,'duyvu1105/typepro-graph-v1-final',public=False)
"""
    return notebook([markdown('# Merge exactly 21 graph experiment partitions'),code(setup),
                     code(graph_auth_source("'duyvu1105'",final=True)),code(execute),code(publish)])
