import copy
import json

import pytest

from typepro.data.preprocess import format_input
from typepro.training.type_changing import Unsupported, augment, build, sha256


def row(code='def f() -> <mask>:\n    return "hello"\n', label='str', candidates=None):
    r = dict(id='owner/repo:f', project='owner/repo', target_function='f', target_name='f',
             target_scope='return', interprocedural_slice=code,
             recommendation_types=candidates or [], label=label)
    r['input'] = format_input('f', 'f', 'return', code, r['recommendation_types'])
    return r


@pytest.mark.parametrize('op,label,expression', [
    ('wrap-list', 'List[str]', '[("hello")]'),
    ('wrap-dict', 'Dict[str, str]', '{"value": ("hello")}'),
])
def test_wrapper_preserves_original_and_changes_verified_label(op, label, expression):
    source = row()
    before = copy.deepcopy(source)
    result = augment(source, op)
    assert source == before
    assert result['label'] == label
    assert expression in result['interprocedural_slice']
    assert result['type_intervention']['parent_id'] == source['id']
    assert result['id'] != source['id']
    assert result['input'] == format_input('f', 'f', 'return', result['interprocedural_slice'], [])


def test_all_return_paths_are_changed():
    source = row('def f(flag) -> <mask>:\n    if flag:\n        return "a"\n    return "b"\n')
    result = augment(source, 'wrap-list')
    assert result['interprocedural_slice'].count('return [(') == 2


def test_utf8_byte_offsets_and_unrelated_strings_are_preserved():
    source = row('def f() -> <mask>:\n    text = "é🙂"; return "hé🙂"\n')
    result = augment(source, 'wrap-list')
    assert 'text = "é🙂"; return [("hé🙂")]' in result['interprocedural_slice']


def test_literal_elements_and_class_reference():
    changed = augment(row('def f() -> <mask>:\n    return ["a", "b"]\n', 'List[str]'), 'element-float')
    assert changed['label'] == 'List[float]'
    assert 'return [0.0, 1.0]' in changed['input']
    source = row('class Item:\n    pass\ndef f() -> <mask>:\n    return Item()\n', 'Item')
    changed = augment(source, 'instance-class')
    assert changed['label'] == 'Type[Item]'
    assert 'return Item\n' in changed['interprocedural_slice']


@pytest.mark.parametrize('code,label', [
    ('def f() -> <mask>:\n    return unknown()\n', 'str'),
    ('def f(str) -> <mask>:\n    return str(1)\n', 'str'),
    ('from module import str\ndef f() -> <mask>:\n    return str(1)\n', 'str'),
    ('def f() -> <mask>:\n    return "x"\n', 'int'),
    ('def f(x) -> <mask>:\n    if x:\n        return "x"\n', 'str'),
    ('def f(x) -> <mask>:\n    if x:\n        return "x"\n    return 1\n', 'str'),
    ('def f() -> <mask>:\n    return "x"\nf()\n', 'str'),
    ('def f() -> <mask>:\n    return f()\n', 'str'),
    ('@decorate\ndef f() -> <mask>:\n    return "x"\n', 'str'),
    ('async def f() -> <mask>:\n    return "x"\n', 'str'),
    ('def f() -> <mask>:\n    yield "x"\n    return "x"\n', 'str'),
    ('def f() -> <mask>:\n    return\n', 'None'),
    ('def f() -> <mask>:\n    x = ["a"]\n    x.append(1)\n    return x\n', 'List[str]'),
    ('class Item(Base):\n    pass\ndef f() -> <mask>:\n    return Item()\n', 'Item'),
])
def test_uncertain_semantics_are_rejected(code, label):
    with pytest.raises(Unsupported):
        augment(row(code, label), 'wrap-list')


def test_exact_candidate_copy_is_synchronized_and_ambiguous_copy_rejects():
    source = row()
    source['recommendation_types'] = [dict(type='F', definition=source['interprocedural_slice'])]
    changed = augment(source, 'wrap-list')
    assert changed['recommendation_types'][0]['definition'] == changed['interprocedural_slice']
    source['recommendation_types'][0]['definition'] = 'def f() -> <mask>:\n    return 12\n'
    with pytest.raises(Unsupported, match='candidate_copy'):
        augment(source, 'wrap-list')


def test_bundles_fail_closed():
    source = row()
    source['evidence_bundle'] = {}
    with pytest.raises(Unsupported, match='bundle'):
        augment(source, 'wrap-list')


def test_target_docstring_removed_without_touching_other_strings():
    source = row('def f() -> <mask>:\n    """Return a string."""\n    value = "Return a string."\n    return value\n')
    changed = augment(source, 'wrap-list')
    assert '"""Return a string."""' not in changed['input']
    assert 'value = "Return a string."' in changed['input']


def test_builtin_predicate_and_typed_arithmetic():
    source = row('def f(x: int) -> <mask>:\n    return x + 3.5\n', 'float')
    changed = augment(source, 'wrap-list')
    scope = {}
    exec(changed['interprocedural_slice'].replace('<mask>', 'object'), scope)
    assert scope['f'](2) == [5.5]
    assert changed['label'] == 'List[float]'
    source = row('def f(x) -> <mask>:\n    return isinstance(x, str)\n', 'bool')
    assert augment(source, 'wrap-dict')['label'] == 'Dict[str, bool]'


def test_builder_retains_original_lines_and_eval_bytes_and_is_deterministic(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    for split in ('train', 'validation', 'test'):
        (source / f'{split}.jsonl').write_text(json.dumps(row(), ensure_ascii=False) + '\n')
    manifest = {'output': {s: dict(rows=1, file=f'{s}.jsonl', sha256=sha256(source / f'{s}.jsonl'))
                           for s in ('train', 'validation', 'test')}}
    (source / 'manifest.json').write_text(json.dumps(manifest))
    a, b = tmp_path / 'a', tmp_path / 'b'
    first, second = build(source, a), build(source, b)
    assert first == second
    assert first['counts']['synthetic_rows'] == 1
    lines = (a / 'train.jsonl').read_text().splitlines(keepends=True)
    assert lines[0] == (source / 'train.jsonl').read_text()
    assert len(lines) == 2
    for split in ('validation', 'test'):
        assert (a / f'{split}.jsonl').read_bytes() == (source / f'{split}.jsonl').read_bytes()
    assert json.loads((a / 'manifest.json').read_text())['output']['train']['rows'] == 2
    with pytest.raises(FileExistsError):
        build(source, a)
