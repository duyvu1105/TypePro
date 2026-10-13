"""Evidence channel contracts, with unsafe-resolution and masking controls."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'Python'))
from check_evidence_inventory import INVENTORY, audit_case, sample


@pytest.mark.parametrize('case', INVENTORY, ids=lambda c: c['id'])
def test_inventory_and_annotation_independence(case, tmp_path):
    first = audit_case(case, tmp_path, 'HiddenGoldA')
    second = audit_case(case, tmp_path, 'CompletelyDifferentGold')
    assert first['passed'], first
    assert second['passed'], second
    assert first['slice'] == second['slice']
    assert [(c['name'], c['definition']) for c in first['candidates']] == [
        (c['name'], c['definition']) for c in second['candidates']]


@pytest.mark.parametrize('change', [
    'def target(decode, value: HiddenGold): return decode(value)',
    'def target(value: HiddenGold):\n    if False: decode = other\n    return decode(value)',
    'decode = other\ndef target(value: HiddenGold): return decode(value)',
])
def test_external_contract_never_bypasses_shadowing(change, tmp_path):
    case = copy.deepcopy(next(c for c in INVENTORY if c['id'] == 'external_root_contract'))
    case['sources']['app.py'] = 'from extlib import decode\n' + change + '\n'
    case['policy'] = 'removed_reasonably'
    assert audit_case(case, tmp_path)['passed']


@pytest.mark.parametrize('change', [
    '    obj = other\n',
    '    obj.normalize = other\n',
    '    Formatter = other\n',
])
def test_receiver_rebinding_prevents_contract(change, tmp_path):
    case = copy.deepcopy(next(c for c in INVENTORY if c['id'] == 'receiver_constructed'))
    case['sources']['app.py'] = case['sources']['app.py'].replace('    return obj.normalize', change + '    return obj.normalize')
    case['policy'] = 'removed_reasonably'
    assert audit_case(case, tmp_path)['passed']


def test_masked_receiver_annotation_cannot_resolve_class(tmp_path):
    case = sample('masked_receiver', 'masking', '''class Formatter:
    def normalize(self, value) -> str: return service(value)
def target(obj: HiddenGold, value): return obj.normalize(value)
''', '-> str', 'removed_reasonably', name='obj')
    hidden = audit_case(case, tmp_path)
    nominal = audit_case(case, tmp_path, 'Formatter')
    # Formatter is independently declared, so its name may legitimately be a candidate.
    assert not any(nominal['channels'].values())
    assert hidden['slice'] == nominal['slice']
    assert [(c['name'], c['definition']) for c in hidden['candidates']] == [
        (c['name'], c['definition']) for c in nominal['candidates']]


def test_single_base_imported_receiver_contract(tmp_path):
    case = sample('inherited', 'signatures', '''from model import Child
def target(value: HiddenGold):
    obj = Child()
    return obj.normalize(value)
''', 'value: bytes')
    case['sources']['model.py'] = '''class Base:
    def normalize(self, value: bytes) -> str: return service(value)
class Child(Base): pass
'''
    assert audit_case(case, tmp_path)['passed']


def test_duplicate_library_contracts_are_ambiguous(tmp_path):
    case = copy.deepcopy(next(c for c in INVENTORY if c['id'] == 'external_root_contract'))
    case['stubs']['extlib'] *= 2
    case['policy'] = 'removed_reasonably'
    assert audit_case(case, tmp_path)['passed']


def test_project_namespace_does_not_use_external_contract(tmp_path):
    case = copy.deepcopy(next(c for c in INVENTORY if c['id'] == 'external_root_contract'))
    case['sources']['extlib.py'] = 'decode = runtime_callable\n'
    case['policy'] = 'removed_reasonably'
    assert audit_case(case, tmp_path)['passed']


def test_hash_inside_string_is_not_a_source_note(tmp_path):
    case = sample('string_hash', 'documentation', '''class Config:
    token = None
    def unused(self): return '# string_note_marker'
def target(config: HiddenGold): return config.token
''', 'string_note_marker', 'removed_reasonably', name='config')
    assert audit_case(case, tmp_path)['passed']
