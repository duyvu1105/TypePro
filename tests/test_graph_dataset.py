from dataclasses import asdict
import json
from pathlib import Path
import subprocess

import pytest

from test_graph_context import Tokenizer
from typepro.analysis.evidence_graph import TargetSpec
from typepro.data.graph_dataset import (export_graph_dataset, verify_graph_dataset, merge_graph_datasets,
                                        freeze_roster, sha256, write_json)


def repository(tmp_path, project='owner/repo'):
    root = tmp_path/'sources'/project
    root.mkdir(parents=True)
    (root/'m.py').write_text('def f(x: int) -> int:\n return x\n')
    subprocess.run(['git','init','-q',str(root)], check=True)
    subprocess.run(['git','-C',str(root),'add','m.py'], check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=Test','-c','user.email=test@example.test',
                    'commit','-qm','fixture'], check=True)
    revision = subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'], text=True).strip()
    return root, revision


def roster(project='owner/repo', name='f', scope='return', split='train'):
    target = TargetSpec(project, 'm.py', 'f', scope, name)
    return dict(target=asdict(target), target_id=target.identity, split=split, original_id='fixture:'+name)


def test_export_keeps_every_outcome_and_labels_are_evaluation_only(tmp_path):
    root, sha = repository(tmp_path)
    rows = [roster(),roster(name='missing',scope='arg')]
    labels = {r['target_id']:'Gold' for r in rows}
    manifest = export_graph_dataset(rows, labels, root.parents[1], {'owner/repo':sha}, {'owner/repo':'kb'}, Tokenizer(),tmp_path/'export')
    assert manifest['total_targets'] == 2
    assert manifest['outcomes'] == {'ready':1,'target_not_found':1}
    verify_graph_dataset(tmp_path/'export')
    outcomes = [json.loads(l) for l in (tmp_path/'export/outcomes.jsonl').read_text().splitlines()]
    assert 'Gold' not in outcomes[0]['input']
    assert len((tmp_path/'export/train.jsonl').read_text().splitlines()) == 1
    with pytest.raises(ValueError,match='new/empty'):
        export_graph_dataset(rows,labels,root.parents[1],{'owner/repo':sha},{'owner/repo':'kb'},Tokenizer(),tmp_path/'export')


def test_exact_merge_and_mixed_tokenizer_rejection(tmp_path):
    root, sha = repository(tmp_path)
    rows = [roster(),roster(name='x',scope='arg')]
    labels = {r['target_id']:'str' for r in rows}
    inputs = []
    for index,row in enumerate(rows):
        path = tmp_path/f'part{index}'
        export_graph_dataset([row],labels,root.parents[1],{'owner/repo':sha},{'owner/repo':'kb'},Tokenizer(),path)
        inputs.append(path)
    merged = merge_graph_datasets(inputs,tmp_path/'merged',rows)
    assert merged['total_targets'] == 2
    with pytest.raises(ValueError,match='exact global roster'):
        merge_graph_datasets(inputs[:1],tmp_path/'missing',rows)
    with pytest.raises(ValueError,match='Overlapping'):
        merge_graph_datasets([inputs[0],tmp_path/'merged'],tmp_path/'overlap',rows)
    tokenizer = Tokenizer(); tokenizer.chat_template = 'different'
    export_graph_dataset([rows[1]],labels,root.parents[1],{'owner/repo':sha},{'owner/repo':'kb'},tokenizer,tmp_path/'different')
    with pytest.raises(ValueError,match='tokenizer_fingerprint'):
        merge_graph_datasets([inputs[0],tmp_path/'different'],tmp_path/'mixed',rows)


def test_source_lock_and_integrity_are_enforced(tmp_path):
    root, sha = repository(tmp_path)
    row = roster()
    with pytest.raises(ValueError,match='locked revision'):
        export_graph_dataset([row],{row['target_id']:'int'},root.parents[1],{'owner/repo':'wrong'},{'owner/repo':'kb'},Tokenizer(),tmp_path/'bad')
    export_graph_dataset([row],{row['target_id']:'int'},root.parents[1],{'owner/repo':sha},{'owner/repo':'kb'},Tokenizer(),tmp_path/'good')
    (tmp_path/'good/train.jsonl').write_text('')
    with pytest.raises(ValueError,match='hash mismatch'):
        verify_graph_dataset(tmp_path/'good')


def test_frozen_roster_preserves_duplicate_metadata_and_ignores_labels(tmp_path):
    for split in ('train','validation','test'):
        rows = [] if split!='train' else [dict(id=f'p:repos/p/m.py:{i}:f',project='p',target_name='f',
                                             target_function='f',target_scope='return',label=label)
                                        for i,label in enumerate(('int','str'))]
        (tmp_path/f'{split}.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    rows, labels = freeze_roster(tmp_path)
    assert len(rows) == len(labels) == 2
    assert rows[0]['target_id'] != rows[1]['target_id']
    assert all(r['target']['file']=='m.py' and 'label' not in r for r in rows)


def test_timeout_is_an_outcome_and_diagnostics_stay_outside_train_rows(tmp_path,monkeypatch):
    from typepro.analysis.graph_limits import QueryTimeout
    from typepro.analysis.graph_context import GraphContextProject
    root,sha=repository(tmp_path)
    row=roster()
    def timeout(*args,**kwargs):
        raise QueryTimeout('synthetic timeout')
    monkeypatch.setattr(GraphContextProject,'query',timeout)
    manifest=export_graph_dataset([row],{row['target_id']:'int'},root.parents[1],{'owner/repo':sha},
                                  {'owner/repo':'kb'},Tokenizer(),tmp_path/'timed')
    assert manifest['outcomes']=={'timeout':1}
    verify_graph_dataset(tmp_path/'timed')
    assert not (tmp_path/'timed/train.jsonl').read_text()


def test_export_uses_frozen_index_for_read_only_dependency_mount(tmp_path):
    root,sha=repository(tmp_path)
    row=roster()
    baseline=tmp_path/'baseline'
    kb=baseline/'actual-archive-path/owner__repo/knowledge_base.json'
    kb.parent.mkdir(parents=True)
    kb.write_text(json.dumps({'schema_version':'typepro-project-kb-v7-source-evidence','records':[]}))
    write_json(baseline/'project_kb_index.json',{'owner__repo':'old-archive-path/missing.json'})
    manifest=export_graph_dataset([row],{row['target_id']:'int'},root.parents[1],
        {'owner/repo':sha},{'owner/repo':sha256(kb)},Tokenizer(),tmp_path/'export',
        dependency_root=baseline,dependency_index={'owner__repo':kb.relative_to(baseline).as_posix()})
    assert manifest['dependency_kb_attached']
    index=json.loads((tmp_path/'export/project_kb_index.json').read_text())
    assert (tmp_path/'export'/index['owner__repo']).read_bytes()==kb.read_bytes()
    verify_graph_dataset(tmp_path/'export')
