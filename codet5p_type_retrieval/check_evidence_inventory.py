"""Audit evidence channels, including intentional removal and candidate transfer.

Run the same cases with --python-dir against a historical snapshot. The verdict
describes the current policy; baseline output is for channel comparison only.
"""
from __future__ import annotations
import argparse
import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from check_evidence_regressions import CASES, replay, implementation_fingerprint


def sample(identifier, group, source, evidence, policy='retained', scope='arg', name='value', **extra):
    return dict(id=identifier, project='inventory', file='app.py', function='target',
                scope=scope, name=name, sources={'app.py': source}, required=[],
                group=group, evidence=evidence, policy=policy, **extra)


INVENTORY = [dict(copy.deepcopy(case), group={
    'superset_collection': 'target_operations', 'workshop_range': 'actual_arguments',
    'workshop_newtype': 'aliases', 'foolbox_tuple_alias': 'aliases',
    'subhub_symlink': 'import_binding', 'mapping_constructor': 'actual_arguments',
    'adventofcode_lambda': 'signatures', 'nicecream_wildcards': 'import_binding',
    'mort_documented_caller': 'documentation',
}[case['id']], policy='retained', evidence=case['required'][0][1]) for case in CASES]

INVENTORY += [
    sample('actual_str', 'actual_arguments', '''def target(value: HiddenGold): return value
target(str(42))
''', 'target(str(42))'),
    sample('external_root_contract', 'signatures', '''from extlib import decode
def target(value: HiddenGold): return decode(value)
''', 'value: bytes', stubs={'extlib': [dict(type='function', name='decode', signature='function decode(value: bytes) -> str')]}),
    sample('external_submodule_alias', 'signatures', '''from extlib.codec import decode as dec
def target(value: HiddenGold): return dec(value)
''', 'value: bytes', stubs={'extlib': [dict(type='function', name='decode', module='extlib.codec', qualified_name='extlib.codec.decode', signature='def decode(value: bytes) -> str:')]}),
    sample('external_wrong_submodule', 'binding_safety', '''from extlib.other import decode
def target(value: HiddenGold): return decode(value)
''', 'value: bytes', 'removed_reasonably', stubs={'extlib': [dict(type='function', name='decode', signature='function decode(value: bytes) -> str')]}),
    sample('receiver_constructed', 'signatures', '''class Formatter:
    def normalize(self, value: bytes) -> str: return service(value)
def target(value: HiddenGold):
    obj = Formatter()
    return obj.normalize(value)
''', '-> str'),
    sample('receiver_self', 'signatures', '''class Formatter:
    def normalize(self, value: bytes) -> str: return service(value)
    def target(self, value: HiddenGold): return self.normalize(value)
''', '-> str'),
    sample('receiver_nominal_contract', 'signatures', '''class Formatter:
    def normalize(self, value) -> str: return service(value)
def target(obj: Formatter, value) -> HiddenGold: return obj.normalize(value)
''', '-> str', scope='return', name='target'),
    sample('receiver_unknown', 'binding_safety', '''class Formatter:
    def normalize(self, value) -> str: return service(value)
def target(obj, value) -> HiddenGold: return obj.normalize(value)
''', '-> str', 'removed_reasonably', scope='return', name='target'),
    sample('custom_union_alias', 'aliases', '''class Space: pass
class Comment: pass
Trivia = Space | Comment
def target(trivia: HiddenGold): return trivia
''', 'Trivia', name='trivia'),
    sample('awaitable_alias', 'aliases', '''from typing import Awaitable
Job = Awaitable[str]
def target(job: HiddenGold): return job
''', 'Job', name='job'),
    sample('explicit_alias', 'aliases', '''from typing import TypeAlias
Item: TypeAlias = str | bytes
def target(item: HiddenGold): return item
''', 'Item', name='item'),
    sample('runtime_indexing_not_alias', 'binding_safety', '''Settings = runtime['x']
def target(settings: HiddenGold): return settings
''', 'class Settings', 'removed_reasonably', name='settings'),
    sample('literal_true_definition', 'import_binding', '''if True:
    def normalize(value: str): return value
def target(value: HiddenGold): return normalize(value)
''', 'value: str'),
    sample('runtime_conditional_definition', 'binding_safety', '''if enabled:
    def normalize(value: str): return value
def target(value: HiddenGold): return normalize(value)
''', 'value: str', 'removed_reasonably'),
    sample('parameter_shadowing', 'binding_safety', '''def convert(value: bytes) -> str: return service(value)
def target(convert, value: HiddenGold): return convert(value)
''', 'value: bytes', 'removed_reasonably'),
    sample('class_source_comment', 'documentation', '''class Config:
    # token holds a text identifier
    token = None
def target(config: HiddenGold): return config.token
''', 'token holds a text identifier', name='config'),
    sample('unrelated_member_comment', 'pruning', '''class Config:
    token = None
    def unused(self):
        # unrelated_member_marker
        return 1
def target(config: HiddenGold): return config.token
''', 'unrelated_member_marker', 'removed_reasonably', name='config'),
    sample('unrelated_target_statement', 'pruning', '''def target(value: HiddenGold):
    log('unrelated_debug_marker')
    return value
''', 'unrelated_debug_marker', 'removed_reasonably'),
    sample('similar_class_to_candidates', 'retrieval', '''class Widget:
    def describe(self): return service()
def target(widget: HiddenGold): return widget
''', 'class Widget', 'candidates', name='widget'),
    sample('constructor_to_candidates', 'retrieval', '''class User:
    def __init__(self, uid: str): self.uid = uid
def target(uid: HiddenGold): return User(uid)
''', 'uid: str', 'candidates', name='uid'),
    sample('candidate_8k_tradeoff', 'candidate_budget', 'class Parser:\n    def parse(self):\n        payload = "body_evidence_marker' + 'x' * 9000 + '"\n        return payload\ndef target(parser: HiddenGold): return parser\n',
           'body_evidence_marker', 'budget_tradeoff', name='parser'),
    sample('nested_lambda_contract', 'unsupported', '''def convert(item: int) -> str: return service(item)
def target(items: HiddenGold): return map(lambda item: convert(item), items)
''', 'item: int', 'unchanged_unsupported', name='items'),
]


def audit_case(case, root, annotation='HiddenGold'):
    stub_dir = root / '_library_contracts'
    stub_dir.mkdir(parents=True, exist_ok=True)
    for package, records in case.get('stubs', {}).items():
        (stub_dir / f'{package}.json').write_text(json.dumps(records), encoding='utf-8')
    with patch.dict(os.environ, {'TYPEPRO_THIRD_PARTY_DATASET': str(stub_dir)}):
        result = replay(case, root, annotation)
    evidence_channels = []
    for needle in dict.fromkeys([case['evidence'], *(text for _, text in case['required'])]):
        evidence_channels.append(dict(evidence=needle,
            slice=needle in result['slice'],
            candidates=any(needle in c['definition'] or needle == c['name'] for c in result['candidates'])))
    channels = {key: evidence_channels[0][key] for key in ('slice', 'candidates')}
    policy = case['policy']
    if policy == 'retained':
        verdict = any(channels.values())
    elif policy == 'candidates':
        verdict = channels['candidates'] and not channels['slice']
    else:
        verdict = not any(channels.values())
    result.update(group=case['group'], policy=policy, evidence=case['evidence'], channels=channels,
                  evidence_channels=evidence_channels,
                  passed=result['passed'] and verdict)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'Python')
    args = parser.parse_args()
    sys.path.insert(0, str(args.python_dir.resolve()))
    rows = []
    with tempfile.TemporaryDirectory(prefix='typepro-inventory-') as temporary:
        for case in INVENTORY:
            root = Path(temporary) / case['id']
            root.mkdir()
            rows.append(audit_case(case, root))
    report = dict(scope='systematic source fixtures; classifications refer to current policy; no model inference',
                  implementation_sha256=implementation_fingerprint(args.python_dir.resolve()),
                  passed=sum(r['passed'] for r in rows), total=len(rows), cases=rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'], total=report['total'])))
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
