import hashlib
import json
from pathlib import Path
import sys
import zipfile

import pytest

from typepro.analysis.project_kb import SCHEMA_VERSION
from typepro.analysis.import_analyzer import importAnalyzer
from typepro.data.kb_reuse import attached_build, reuse_project_kb
from typepro.data import prepare

SCHEMA = 'typepro-project-kb-top10-generative-v17-catalog-fallback-audit'
COMMIT = 'a' * 40


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def frozen(root):
    records = [dict(type='class', kind='class', name='Plot', qualified_name='external.Plot',
                    package='external', module='external', source='third_party',
                    definition='class Plot:\n    def render(self): pass',
                    methods=['def render(self):'], fields=[], bases=[]),
               dict(type='function', kind='function', name='make', package='external',
                    signature='def make():', module='external', qualified_name='external.make', source='third_party'),
               dict(type='class', kind='class', name='Local', qualified_name='local.Local',
                    definition='class Local: pass', source='project')]
    write(root/'project_kb/owner__repo/knowledge_base.json',dict(schema_version=SCHEMA_VERSION,record_count=3,records=records))
    write(root/'project_status/owner__repo.json',dict(project='owner/repo',commit=COMMIT,retrieval_schema_version=SCHEMA))
    write(root/'runtime_manifest.json',dict(retrieval_schema_version=SCHEMA,
        candidate_policy_version='candidate-symbol-v2',context_policy_version='ast-context-v7-verified-signature-evidence'))
    write(root/'shard_manifest.json',dict(shard_index=12,shard_count=40,missing_projects=[]))
    return records


def test_reuse_preserves_exact_kb_and_restores_import_semantics(tmp_path, monkeypatch):
    source=tmp_path/'source';records=frozen(source);dest=tmp_path/'dest'
    info=reuse_project_kb(source,'owner/repo',COMMIT,dest,SCHEMA)
    original=(source/'project_kb/owner__repo/knowledge_base.json').read_bytes()
    assert (dest/'knowledge_base.json').read_bytes()==original
    assert info['sha256']==hashlib.sha256(original).hexdigest()
    assert json.loads((dest/'imports/external.json').read_text())==records[:2]
    original_imports=tmp_path/'original_imports';write(original_imports/'external.json',records[:2])
    example=tmp_path/'example.py';example.write_text('from external import Plot, make\n')
    monkeypatch.setenv('TYPEPRO_THIRD_PARTY_DATASET',str(original_imports))
    before=importAnalyzer(str(example))
    monkeypatch.setenv('TYPEPRO_THIRD_PARTY_DATASET',str(dest/'imports'))
    after=importAnalyzer(str(example))
    assert len(before.total_data)==len(after.total_data)==2
    assert [(x.name,getattr(x,'definition',''),getattr(x,'signature','')) for x in before.total_data] == [
        (x.name,getattr(x,'definition',''),getattr(x,'signature','')) for x in after.total_data]


@pytest.mark.parametrize('change', ['commit','schema','runtime','package'])
def test_incompatible_cache_falls_back_without_writing(tmp_path,change):
    source=tmp_path/'source';frozen(source);dest=tmp_path/'dest'
    if change=='commit':commit='b'*40
    else:commit=COMMIT
    if change=='schema':
        p=source/'project_kb/owner__repo/knowledge_base.json';kb=json.loads(p.read_text());kb['schema_version']='old';write(p,kb)
    if change=='runtime':write(source/'runtime_manifest.json',{})
    if change=='package':
        p=source/'project_kb/owner__repo/knowledge_base.json';kb=json.loads(p.read_text());kb['records'][0].pop('package');write(p,kb)
    assert reuse_project_kb(source,'owner/repo',commit,dest,SCHEMA) is None
    assert not dest.exists()


def test_attached_archive_extracts_kb_but_never_old_rows(tmp_path):
    source=tmp_path/'source';frozen(source)
    write(source/'raw_slices/owner__repo.jsonl',{'old':True})
    attached=tmp_path/'input';attached.mkdir()
    with zipfile.ZipFile(attached/'typepro_build_shard_12.zip','w') as archive:
        for p in source.rglob('*'):
            if p.is_file():archive.write(p,Path('build')/p.relative_to(source))
    root=attached_build(attached,tmp_path/'cache',12,40)
    assert (root/'project_kb/owner__repo/knowledge_base.json').exists()
    assert not (root/'raw_slices').exists()
    with pytest.raises(ValueError,match='coordinates'):attached_build(attached,tmp_path/'other',12,20)


def test_archive_traversal_is_rejected(tmp_path):
    with zipfile.ZipFile(tmp_path/'typepro_build_shard_12.zip','w') as archive:archive.writestr('../escape.json','{}')
    with pytest.raises(ValueError,match='Unsafe'):attached_build(tmp_path,tmp_path/'cache',12,40)


def test_pipeline_reuses_kb_but_regenerates_export(tmp_path,monkeypatch):
    source=tmp_path/'source';frozen(source);work=tmp_path/'work'
    monkeypatch.setattr(sys,'argv',['prepare','--reuse-project-kb-from',str(source),'--preview-samples','0'])
    args=prepare.parse_args()
    monkeypatch.setattr(prepare,'load_prepared_annotations',lambda _: [dict(file='repos/owner/repo/main.py',loc='f@global',name='x',scope='arg',cat='user-defined',gttype='Plot')])
    monkeypatch.setattr(prepare,'clone_project',lambda *a,**k:COMMIT)
    commands=[]
    def run(command,*a,**kwargs):
        commands.append(list(map(str,command)))
        assert 'export_slices.py' in str(command[1])
        path=Path(command[command.index('--output')+1]);path.write_text('{"new":true}\n')
        return '{"eligible":1,"written":1}'
    monkeypatch.setattr(prepare,'run_logged',run)
    monkeypatch.setattr(prepare,'safe_remove_repo',lambda *a:None)
    prepare.slice_projects(args,work,Path(__file__).resolve().parents[1])
    assert len(commands)==1
    status=json.loads((work/'project_status/owner__repo.json').read_text())
    assert status['candidate_policy_version']=='candidate-lexical-v3'
    assert status['kb_reuse']['sha256']==hashlib.sha256((source/'project_kb/owner__repo/knowledge_base.json').read_bytes()).hexdigest()
    assert (work/'raw_slices/owner__repo.jsonl').read_text()=='{"new":true}\n'
