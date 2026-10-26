"""Fixed-roster graph exports, outcome ledger, verification, and strict merging.

Run with --help. This experiment entrypoint never invokes the legacy slicer and
never drops a roster target. Labels are attached only after graph selection.
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import sys
import json
from pathlib import Path
import subprocess
import time
import shutil
import tokenize
try:
    import resource
except ImportError:
    resource = None

from typepro.analysis.evidence_graph import POLICY, SCHEMA, OUTCOMES, TargetSpec, digest
from typepro.analysis.graph_context import GraphContextProject
from typepro.analysis.graph_limits import query_deadline, QueryTimeout
from typepro.shared.context_packing import tokenizer_fingerprint, VERSION as BUDGET_POLICY

DATASET_SCHEMA = 'typepro-graph-dataset-v1'
LOCK_FIELDS = ('implementation_sha','implementation_fingerprint','python_version','context_policy_version', 'graph_schema', 'budget_policy', 'tokenizer_fingerprint',
               'source_lock_hash', 'dependency_lock_hash', 'roster_hash', 'input_length', 'label_length')


def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        while block := handle.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def freeze_roster(baseline):
    """Extract target identities and labels, without consulting predictions/types.

    Historical exports only preserve source paths within their stable IDs. Use
    that path plus qualified function and scope/name, never the export row index.
    Original record IDs preserve duplicate metadata annotations without treating
    them as distinct source definitions. Repeated source definitions require an
    explicit occurrence; otherwise they receive target_not_found, never a guess.
    """
    baseline = Path(baseline)
    baseline_manifest=baseline/'manifest.json'
    if baseline_manifest.exists():
        manifest=json.loads(baseline_manifest.read_text())
        for split in ('train','validation','test'):
            expected=manifest['output'][split]
            if sha256(baseline/expected['file'])!=expected['sha256']:
                raise ValueError('Frozen baseline split hash mismatch: '+split)
    roster, labels, seen = [], {}, set()
    for split in ('train', 'validation', 'test'):
        for row in read_jsonl(baseline / f'{split}.jsonl'):
            if row.get('file'):
                file = row['file']
            else:
                # Stable legacy identity is project:file:line:name; the line is
                # not used as target identity or as a graph-selection feature.
                file = row['id'].split(':', 3)[1]
            prefix = f"repos/{row['project']}/"
            if file.startswith(prefix):
                file = file[len(prefix):]
            elif file.startswith(row['project'] + '/'):
                file = file[len(row['project']) + 1:]
            target = TargetSpec(row['project'], file, row['target_function'], row['target_scope'],
                                row['target_name'], row.get('target_occurrence'), row['id'])
            if target.identity in seen:
                raise ValueError('Ambiguous duplicate roster identity; provide definition occurrence explicitly')
            seen.add(target.identity)
            roster.append(dict(target=asdict(target), target_id=target.identity, split=split, original_id=row['id']))
            labels[target.identity] = row['label']
    return roster, labels


def training_row(row):
    """Keep diagnostics in the outcome ledger rather than the model dataset."""
    keys=('id','target_id','target','project','split','outcome','input','label',
          'context_policy_version','graph_schema','budget_policy','tokenizer_fingerprint',
          'source_commit','source_hash','dependency_hash','input_length','label_length','cache_key')
    return {key:row[key] for key in keys if key in row}


def verify_graph_dataset(root, tokenizer=None):
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text())
    if manifest.get('schema_version') != DATASET_SCHEMA or manifest.get('context_policy_version') != POLICY:
        raise ValueError('Incompatible graph dataset schema/policy')
    for key, expected in manifest['files'].items():
        if not (root/key).resolve().is_relative_to(root.resolve()):
            raise ValueError('Graph manifest path escapes dataset')
        if sha256(root / key) != expected:
            raise ValueError(f'Graph dataset hash mismatch: {key}')
    for name,key in (('source_locks.json','source_lock_hash'),('dependency_locks.json','dependency_lock_hash')):
        if digest(json.loads((root/name).read_text()))!=manifest[key]:
            raise ValueError('Graph lock fingerprint mismatch')
    source_locks=json.loads((root/'source_locks.json').read_text())
    dependency_locks=json.loads((root/'dependency_locks.json').read_text())
    index=json.loads((root/'project_kb_index.json').read_text())
    for project,relative in index.items():
        path=root/relative
        if not path.resolve().is_relative_to(root.resolve()) or relative not in manifest['files']:
            raise ValueError('Unverified graph KB path')
        original=project.replace('__','/',1)
        # Project spellings are taken from the roster below for repositories
        # containing underscores; the digest still binds the exact file.
        if original in dependency_locks and sha256(path)!=dependency_locks[original]:
            raise ValueError('Graph KB dependency fingerprint mismatch')
    if tokenizer is not None and tokenizer_fingerprint(tokenizer)!=manifest['tokenizer_fingerprint']:
        raise ValueError('Verification tokenizer fingerprint mismatch')
    roster = list(read_jsonl(root / 'roster.jsonl'))
    expected = {r['target_id']: r for r in roster}
    if len(expected) != len(roster):
        raise ValueError('Duplicate roster target')
    if digest(roster) != manifest['roster_hash']:
        raise ValueError('Roster fingerprint mismatch')
    actual={}
    counts=Counter()
    ready_ids={split:set() for split in ('train','validation','test')}
    split_projects = {}
    for row in read_jsonl(root/'outcomes.jsonl'):
        if row['target_id'] in actual or row['target_id'] not in expected:
            raise ValueError('Outcome ledger has duplicate/unknown target')
        actual[row['target_id']]=digest(training_row(row))
        counts[row['outcome']]+=1
        if row['outcome'] in {'ready','unresolved'}:
            ready_ids[row['split']].add(row['target_id'])
        target = TargetSpec(**row['target'])
        if target.identity != row['target_id'] or row['target'] != expected[target.identity]['target']:
            raise ValueError('Target identity mismatch')
        if target.project not in source_locks or target.project not in dependency_locks:
            raise ValueError('Missing project lock in graph dataset')
        if row.get('source_commit') not in (None,source_locks[target.project]) or row.get('dependency_hash') not in (None,dependency_locks[target.project]):
            raise ValueError('Row source/dependency fingerprint mismatch')
        if manifest.get('dependency_kb_attached') and target.project.replace('/','__') not in index:
            raise ValueError('Missing frozen project KB')
        if row['outcome'] not in OUTCOMES or row['split'] != expected[target.identity]['split']:
            raise ValueError('Invalid outcome or changed split')
        if manifest.get('partition'):
            physical=manifest['partition']
            number=int(hashlib.sha1(('17:'+target.project).encode()).hexdigest()[:16],16)
            if number%physical['shard_count']!=physical['shard_index']:
                raise ValueError('Target belongs to another physical partition')
        project = target.project.casefold()
        if project in split_projects and split_projects[project] != row['split']:
            raise ValueError('Project split overlap')
        split_projects[project] = row['split']
        for key in ('context_policy_version', 'graph_schema', 'budget_policy', 'tokenizer_fingerprint', 'input_length', 'label_length'):
            if row.get(key) != manifest.get(key):
                raise ValueError(f'Mixed graph fingerprint: {key}')
        if row['outcome'] in {'ready', 'unresolved'}:
            if not row.get('input') or row['audit']['prompt_tokens'] > manifest['input_length'] - manifest['label_length']:
                raise ValueError('Invalid packed ready prompt')
            if tokenizer is not None:
                from typepro.shared.context_packing import prompt_token_ids
                actual_tokens=prompt_token_ids(tokenizer,row['input'],manifest['input_length'],manifest['label_length'])
                if len(actual_tokens)!=row['audit']['prompt_tokens']:
                    raise ValueError('Packed prompt token count mismatch')
            groups={g['id']:g for g in row['full_evidence']}
            retained=set(row['audit']['retained_groups'])
            if not retained<=groups.keys() or any(g['mandatory'] and k not in retained for k,g in groups.items()):
                raise ValueError('Missing mandatory evidence group')
            if any(not set(groups[k]['prerequisites'])<=retained for k in retained):
                raise ValueError('Missing retained evidence prerequisite')
            graph = row['audit']['graph']
            nodes = {n['id'] for n in graph['nodes']}
            if not set(graph['seeds'])<=nodes or any(g['node'] not in nodes or g['unresolved_node'] not in nodes for g in graph['gaps']):
                raise ValueError('Broken graph seed or unresolved provenance')
            if any(e['source'] not in nodes or e['target'] not in nodes for e in graph['edges']):
                raise ValueError('Broken evidence path')
    if actual.keys()!=expected.keys():
        raise ValueError('Outcome ledger does not cover exact roster')
    if manifest['total_targets']!=len(roster) or manifest['outcomes']!=dict(counts):
        raise ValueError('Graph manifest outcome totals differ from ledger')
    for split in ('train','validation','test'):
        seen=set()
        for row in read_jsonl(root/f'{split}.jsonl'):
            identifier=row['target_id']
            if identifier in seen or identifier not in ready_ids[split]:
                raise ValueError('Ready rows differ from ledger')
            seen.add(identifier)
            if digest(row)!=actual[identifier]:
                raise ValueError('Split row differs from audited outcome')
        if seen!=ready_ids[split]:
            raise ValueError('Ready rows differ from ledger')
    return manifest


def export_graph_dataset(roster, labels, repos_root, source_locks, dependency_locks, tokenizer, output,
                         input_length=6144, label_length=64, max_expansions=32, dependency_root=None, clone_missing=False, partition=None, annotation_timeout_seconds=30):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Graph output directory must be new/empty; preserve previous experiment artifacts')
    output.mkdir(parents=True, exist_ok=True)
    ids = [TargetSpec(**r['target']).identity for r in roster]
    if len(set(ids)) != len(ids) or any(i != r['target_id'] for i, r in zip(ids, roster)):
        raise ValueError('Invalid or duplicate roster identities')
    implementation_root=Path(__file__).resolve().parents[2]
    implementation_sha=subprocess.check_output(['git','-C',str(implementation_root),'rev-parse','HEAD'],text=True).strip()
    implementation_files=[*implementation_root.glob('typepro/analysis/graph*.py'),
                          implementation_root/'typepro/analysis/evidence_graph.py',
                          implementation_root/'typepro/analysis/target_context.py',
                          implementation_root/'typepro/shared/context_packing.py',
                          implementation_root/'typepro/shared/generative_chat.py',Path(__file__)]
    implementation_fingerprint=digest({p.relative_to(implementation_root).as_posix():sha256(p) for p in implementation_files})
    manifest = dict(implementation_sha=implementation_sha, implementation_fingerprint=implementation_fingerprint,
                    python_version=list(sys.version_info[:2]),schema_version=DATASET_SCHEMA, context_policy_version=POLICY, graph_schema=SCHEMA,
                    budget_policy=BUDGET_POLICY, tokenizer_fingerprint=tokenizer_fingerprint(tokenizer),
                    source_lock_hash=digest(source_locks), dependency_lock_hash=digest(dependency_locks),
                    roster_hash=digest(roster), input_length=input_length, label_length=label_length,
                    max_expansions=max_expansions, annotation_timeout_seconds=annotation_timeout_seconds,
                    dependency_kb_attached=dependency_root is not None)
    if partition is not None:
        index,count=partition
        if not 0<=index<count:
            raise ValueError('Invalid physical partition')
        manifest['partition']={'shard_index':index,'shard_count':count}
    write_json(output/'source_locks.json', source_locks)
    write_json(output/'dependency_locks.json', dependency_locks)
    kb_index = {}
    # Process projects together and release catalogs between projects to bound
    # memory; write all ledger entries, including failed outcomes, incrementally.
    projects = {}
    for row in roster:
        projects.setdefault(row['target']['project'], []).append(row)
    handles = {s: (output / f'{s}.jsonl').open('w', encoding='utf-8')
               for s in ('train', 'validation', 'test', 'outcomes', 'roster')}
    counts = Counter()
    try:
        for item in roster:
            handles['roster'].write(json.dumps(item, ensure_ascii=False) + '\n')
        for project, items in sorted(projects.items()):
            if project not in source_locks or project not in dependency_locks:
                raise ValueError(f'Missing source/dependency lock for {project}')
            root = Path(repos_root) / project
            created_checkout = False
            if clone_missing and not root.exists():
                from typepro.data.prepare import clone_project
                clone_project(project, root, timeout_seconds=120, expected_commit=source_locks[project])
                created_checkout = True
            revision = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], check=True,
                                      capture_output=True, text=True).stdout.strip()
            dirty = subprocess.run(['git', '-C', str(root), 'status', '--porcelain'], check=True,
                                   capture_output=True, text=True).stdout.strip()
            if revision != source_locks[project] or dirty:
                raise ValueError(f'Project checkout is not the clean locked revision: {project}')
            tracked = subprocess.check_output(['git','-C',str(root),'ls-files','-z'], text=True).split('\0')
            sources = {}
            for file in tracked:
                path = root/file
                if path.suffix in {'.py','.pyi'} and path.is_file() and path.resolve().is_relative_to(root.resolve()):
                    try:
                        with tokenize.open(path) as source_file:
                            sources[file] = source_file.read()
                    except (UnicodeDecodeError,SyntaxError,LookupError):
                        sources[file] = 'invalid python source encoding!'
            dependency_kb = None
            if dependency_root is not None:
                kb_root = Path(dependency_root)
                index_file = kb_root/'project_kb_index.json'
                index = json.loads(index_file.read_text()) if index_file.exists() else {}
                key = project.replace('/','__')
                relative = index.get(key, f'project_kb/{key}/knowledge_base.json')
                if not isinstance(relative,str):
                    raise ValueError('Unexpected project KB index entry')
                kb_path = kb_root/relative
                if not kb_path.resolve().is_relative_to(kb_root.resolve()) or sha256(kb_path) != dependency_locks[project]:
                    raise ValueError(f'Frozen dependency KB mismatch: {project}')
                destination = output/'project_kb'/digest(project)/'knowledge_base.json'
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(kb_path, destination)
                kb_index[key] = destination.relative_to(output).as_posix()
                dependency_kb = json.loads(kb_path.read_text())
                if dependency_kb.get('schema_version') != 'typepro-project-kb-v7-source-evidence':
                    raise ValueError('Rebuild incompatible dependency KB; never restamp legacy data')
            from typepro.analysis.project_index import project_module_aliases
            context = GraphContextProject(project, sources, revision, dependency_locks[project], max_expansions, dependency_kb,project_module_aliases(root))
            for item in items:
                target = TargetSpec(**item['target'])
                started = time.monotonic()
                try:
                    with query_deadline(annotation_timeout_seconds):
                        result = context.query(target, tokenizer, input_length, label_length)
                except QueryTimeout:
                    result=dict(target=item['target'],target_id=target.identity,outcome='timeout',input=None,
                                gaps=[dict(reason='graph_target_deadline')])
                except (SyntaxError, ValueError) as error:
                    # An annotation overlay parse failure remains visible in the
                    # fixed roster; unexpected implementation errors propagate.
                    if not isinstance(error, SyntaxError):
                        raise
                    result = dict(target=item['target'], target_id=target.identity, outcome='parse_error', input=None,
                                  gaps=[dict(reason=type(error).__name__)])
                for key in ('context_policy_version', 'graph_schema', 'budget_policy', 'tokenizer_fingerprint', 'input_length', 'label_length'):
                    result[key] = manifest[key]
                result.update(split=item['split'], project=project, id=item['original_id'],
                              label=labels[target.identity], elapsed_seconds=time.monotonic() - started)
                line = json.dumps(result, ensure_ascii=False) + '\n'
                handles['outcomes'].write(line)
                if result['outcome'] in {'ready', 'unresolved'}:
                    handles[item['split']].write(json.dumps(training_row(result),ensure_ascii=False)+'\n')
                counts[result['outcome']] += 1
            del context
            if created_checkout:
                shutil.rmtree(root)
    finally:
        for handle in handles.values():
            handle.close()
    write_json(output/'project_kb_index.json',kb_index)
    manifest.update(peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource else None, outcomes=dict(counts), total_targets=len(roster),
                    files={p.relative_to(output).as_posix(): sha256(p) for p in output.rglob('*') if p.is_file() and p.name!='manifest.json'})
    write_json(output / 'manifest.json', manifest)
    verify_graph_dataset(output,tokenizer)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clone-missing', action='store_true', help='Clone exact locked projects into a new temporary source cache')
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--repos-root', required=True, type=Path)
    parser.add_argument('--source-lock', required=True, type=Path, help='JSON project -> exact commit')
    parser.add_argument('--dependency-lock', required=True, type=Path, help='JSON project -> frozen KB SHA256')
    parser.add_argument('--dependency-root', required=True, type=Path, help='Frozen baseline project KB directory')
    parser.add_argument('--tokenizer', required=True, help='Local frozen tokenizer directory')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--input-length', type=int, default=6144)
    parser.add_argument('--label-length', type=int, default=64)
    parser.add_argument('--annotation-timeout-seconds',type=float,default=30)
    parser.add_argument('--max-expansions', type=int, default=32)
    args = parser.parse_args()
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True)
    roster, labels = freeze_roster(args.baseline)
    manifest = export_graph_dataset(roster, labels, args.repos_root, json.loads(args.source_lock.read_text()),
        json.loads(args.dependency_lock.read_text()), tokenizer, args.output,
        args.input_length, args.label_length, args.max_expansions, args.dependency_root, args.clone_missing, annotation_timeout_seconds=args.annotation_timeout_seconds)
    print(json.dumps(manifest, indent=2))




def merge_graph_datasets(inputs, output, roster):
    """Merge exactly the planned inputs into the frozen global target roster."""
    roots = [Path(p) for p in inputs]
    manifests = [verify_graph_dataset(p) for p in roots]
    if not roots or len(set(p.resolve() for p in roots)) != len(roots):
        raise ValueError('Require distinct graph merge inputs')
    comparable = set(LOCK_FIELDS) - {'roster_hash'}
    comparable.update({'max_expansions','annotation_timeout_seconds','dependency_kb_attached'})
    for key in comparable:
        if len({json.dumps(m.get(key), sort_keys=True) for m in manifests}) != 1:
            raise ValueError(f'Mismatched graph merge fingerprint: {key}')
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Merge output must be new/empty')
    expected = {r['target_id']: r for r in roster}
    if len(expected) != len(roster):
        raise ValueError('Duplicate global roster identity')
    actual = {}
    counts=Counter()
    for root in roots:
        for item in read_jsonl(root / 'roster.jsonl'):
            if expected.get(item['target_id']) != item:
                raise ValueError('Shard roster differs from frozen global roster')
        with (root/'outcomes.jsonl').open('rb') as ledger:
            while True:
                offset=ledger.tell()
                line=ledger.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                row=json.loads(line)
                if row['target_id'] in actual:
                    raise ValueError('Overlapping graph merge targets')
                actual[row['target_id']]=(root,offset)
                counts[row['outcome']]+=1
    if actual.keys() != expected.keys():
        raise ValueError('Graph merge does not cover exact global roster')
    output.mkdir(parents=True, exist_ok=True)
    handles = {s: (output / f'{s}.jsonl').open('w', encoding='utf-8')
               for s in ('train', 'validation', 'test', 'outcomes', 'roster')}
    from contextlib import ExitStack
    with ExitStack() as readers:
        ledgers={root:readers.enter_context((root/'outcomes.jsonl').open('rb')) for root in roots}
        try:
            for item in roster:
                root,offset=actual[item['target_id']]
                ledgers[root].seek(offset)
                row=json.loads(ledgers[root].readline())
                handles['roster'].write(json.dumps(item, ensure_ascii=False) + '\n')
                line = json.dumps(row, ensure_ascii=False) + '\n'
                handles['outcomes'].write(line)
                if row['outcome'] in {'ready', 'unresolved'}:
                    handles[row['split']].write(json.dumps(training_row(row),ensure_ascii=False)+'\n')
        finally:
            for handle in handles.values():
                handle.close()
    kb_index = {}
    for root in roots:
        for name in ('source_locks.json','dependency_locks.json'):
            destination = output/name
            if destination.exists() and sha256(destination)!=sha256(root/name):
                raise ValueError('Graph lock content collision')
            shutil.copyfile(root/name,destination)
        source_index = json.loads((root/'project_kb_index.json').read_text())
        for key,relative in source_index.items():
            if key in kb_index and kb_index[key]!=relative:
                raise ValueError('Graph KB index collision')
            destination=output/relative
            destination.parent.mkdir(parents=True,exist_ok=True)
            if destination.exists() and sha256(destination)!=sha256(root/relative):
                raise ValueError('Graph KB content collision')
            shutil.copyfile(root/relative,destination)
            kb_index[key]=relative
    write_json(output/'project_kb_index.json',kb_index)
    manifest = dict(manifests[0], roster_hash=digest(roster), total_targets=len(roster),
                    outcomes=dict(counts),
                    merge_inputs=[dict(path=str(p), manifest_sha256=sha256(p/'manifest.json')) for p in roots],
                    files={p.relative_to(output).as_posix(): sha256(p) for p in output.rglob('*') if p.is_file() and p.name!='manifest.json'})
    manifest.pop('partition',None)
    write_json(output / 'manifest.json', manifest)
    return verify_graph_dataset(output)


if __name__ == '__main__':
    main()
