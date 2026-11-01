import ast
import copy
import json

import pytest

from typepro.training.contract_changing import POLICY, Unsupported, augment, build, transform, candidate_from_target_file
from typepro.training.type_changing import sha256
from test_type_changing import row


def execute(code, scope=None):
    scope = dict(scope or {})
    exec(code.replace('<mask>', 'object'), scope)
    return scope


@pytest.mark.parametrize('operation,label', [('wrap-list','List[Widget]'), ('wrap-dict','Dict[str, Widget]')])
def test_source_label_is_an_assumed_contract_not_reinferred(operation,label):
    source = row('def f(x) -> <mask>:\n    return opaque_external_api(x)\n', 'Widget')
    before = copy.deepcopy(source)
    result = augment(source, operation)
    assert result['label'] == label and source == before
    assert result['type_intervention']['verification'].startswith('assumed-source-contract')


@pytest.mark.parametrize('op', ['wrap-list','wrap-dict'])
def test_direct_keyword_and_recursive_callers_keep_original_values(op):
    code = 'def f(x) -> <mask>:\n    if x <= 0:\n        return 1\n    return x * f(x=x-1)\ndef caller():\n    return f(x=4) + 1\n'
    source = row(code, 'int')
    original = execute(code)
    result = augment(source, op)
    changed = execute(result['interprocedural_slice'])
    assert original['caller']() == changed['caller']() == 25
    unwrapped = changed['f'](4)[0] if op == 'wrap-list' else changed['f'](4)['value']
    assert unwrapped == 24
    assert result['type_intervention']['stats']['callers'] == 2


def test_shadowed_local_function_calls_are_untouched():
    code = 'def f() -> <mask>:\n    return 2\ndef other(f):\n    return f()\nx=f()\n'
    changed = augment(row(code,'int'), 'wrap-list')['interprocedural_slice']
    assert 'return f()\n' in changed
    assert 'x=f()[0]' in changed
    scope=execute(changed)
    assert scope['x']==2 and scope['other'](lambda: 7)==7


def test_all_branch_returns_and_nested_function_scopes():
    code='def f(flag) -> <mask>:\n    def helper():\n        return 10\n    if flag:\n        return helper()\n    else:\n        return 3\n'
    changed=augment(row(code,'int'),'wrap-dict')['interprocedural_slice']
    scope=execute(changed)
    assert scope['f'](True)=={'value':10} and scope['f'](False)=={'value':3}
    assert 'return 10\n' in changed


@pytest.mark.parametrize('code',[
 'def f(x) -> <mask>:\n    if x:\n        return 1\n',
 'def f() -> <mask>:\n    return\n',
])
def test_fallthrough_and_bare_return_require_nullable_contract(code):
    with pytest.raises(Unsupported,match='none_path'):
        augment(row(code,'int'),'wrap-list')
    result=augment(row(code,'Optional[int]'),'wrap-list')
    f=execute(result['interprocedural_slice'])['f']
    assert (f(False) if 'x)' in code else f()) == [None]


def test_one_line_docstring_and_bare_return():
    code='def f() -> <mask>: """Old return prose."""; return\n'
    result=augment(row(code,'None'),'wrap-list')
    assert 'Old return prose' not in result['input']
    assert execute(result['interprocedural_slice'])['f']()==[None]


@pytest.mark.parametrize('suffix',[
 'alias=f\n', 'consume(f)\n', 'f=other\n', 'getattr(obj,"f")\n', 'obj.f()\n',
])
def test_unresolved_or_escaping_references_rejected(suffix):
    with pytest.raises(Unsupported):
        augment(row('def f() -> <mask>:\n    return 1\n'+suffix,'int'),'wrap-list')


def test_explicit_class_method_call_resolved_but_instance_dispatch_rejected():
    source=row('class C:\n    def f(self) -> <mask>:\n        return 2\nx=C.f(C())\n','int')
    source['target_function']='C.f'
    changed=augment(source,'wrap-list')
    assert execute(changed['interprocedural_slice'])['x']==2
    source['interprocedural_slice']='class C:\n    def f(self) -> <mask>:\n        return 2\nx=C().f()\n'
    with pytest.raises(Unsupported,match='method_reference'):
        augment(source,'wrap-list')


def test_candidate_reduced_body_and_caller_synchronized():
    source=row('def f(x) -> <mask>:\n    helper=1\n    return opaque(x)\n','Custom')
    source['recommendation_types']=[dict(type='F',definition='def f(x) -> <mask>:\n    return opaque(x)\ndef g():\n    return f(1)\n')]
    result=augment(source,'wrap-list')
    assert 'return [(opaque(x))]' in result['recommendation_types'][0]['definition']
    assert 'return f(1)[0]' in result['recommendation_types'][0]['definition']
    assert result['type_intervention']['synchronized_candidate_copies']==1


def test_unrelated_same_named_method_does_not_get_changed():
    source=row('class C:\n    def f(self) -> <mask>:\n        return 1\n','int')
    source['target_function']='C.f'
    other='class D:\n    def f(self):\n        return "other"\n'
    source['recommendation_types']=[dict(type='D',definition=other)]
    result=augment(source,'wrap-list')
    assert result['recommendation_types'][0]['definition']==other


def test_unbound_candidate_reference_not_assumed_to_be_same_function():
    source=row()
    source['recommendation_types']=[dict(type='Other',definition='def other():\n    return f()\n')]
    with pytest.raises(Unsupported,match='candidate:unresolved'):
        augment(source,'wrap-list')


class Tokenizer:
    name_or_path='test-tokenizer'
    def apply_chat_template(self,messages,**kwargs):
        text=''.join(m['content']+'\n' for m in messages if m['role']!='assistant')+'assistant:'
        if not kwargs['add_generation_prompt']:
            text+=messages[-1]['content']+'<end>'
        return list(range(len(text)))


def test_build_is_deterministic_diverse_and_preserves_original_and_eval_bytes(tmp_path):
    source=tmp_path/'source';source.mkdir()
    rows=[]
    for i in range(8):
        r=row();r.update(id=f'project:{i}',project=f'project-{i%2}')
        rows.append(r)
    train=''.join(json.dumps(r)+'\n' for r in rows)
    splits={}
    for s in ['train','validation','test']:
        p=source/f'{s}.jsonl';p.write_text(train if s=='train' else json.dumps(rows[0])+'\n')
        splits[s]=dict(file=p.name,rows=8 if s=='train' else 1,sha256=sha256(p))
    (source/'manifest.json').write_text(json.dumps(dict(output=splits)))
    args=dict(tokenizer=Tokenizer(),prompt_limit=10000,per_project=2,max_synthetic=8)
    a=build(source,tmp_path/'a',**args);b=build(source,tmp_path/'b',**args)
    assert a==b and a['counts']['synthetic_rows']==4
    parallel=build(source,tmp_path/'parallel',workers=2,**args)
    assert parallel['output_hashes']==a['output_hashes']
    assert max(a['projects'].values())==2 and a['readiness']['passed'] is False
    generated=list(map(json.loads,(tmp_path/'a/train.jsonl').read_text().splitlines()))
    assert [r for r in generated if 'type_intervention' not in r]==rows
    for s in ['validation','test']:
        assert (source/f'{s}.jsonl').read_bytes()==(tmp_path/'a'/f'{s}.jsonl').read_bytes()
    assert not (tmp_path/'a/synthetic_pool.jsonl.tmp').exists()
    assert a['policy']==POLICY
    from typepro.audit.contract_changing import audit_dataset
    verified=audit_dataset(source,tmp_path/'a',Tokenizer())
    assert verified['passed'] and verified['counts']['synthetic_rows']==4
    assert verified['readiness']['passed'] is False


def test_annotation_label_not_added_to_input():
    result=augment(row('def f(x) -> <mask>:\n    return opaque(x)\n','SecretNominalType'),'wrap-list')
    assert 'SecretNominalType' not in result['input']


def test_unannotated_copy_requires_file_provenance_and_matching_signature():
    source=row('def f(self, x: int) -> <mask>:\n    return opaque(x)\n','Custom')
    source.update(id='owner/repo:repos/owner/repo/src/pkg/mod.py:123:f',target_function='C.f')
    source['recommendation_types']=[dict(type='C',qualified_name='pkg.mod.C',
        definition='class C:\n    def f(self, x: int):\n        return opaque(x)\n')]
    assert candidate_from_target_file(source,source['recommendation_types'][0])
    result=augment(source,'wrap-list')
    assert 'return [(opaque(x))]' in result['recommendation_types'][0]['definition']
    assert result['type_intervention']['synchronized_candidate_copies']==1
    from typepro.audit.contract_changing import compare_code
    compare_code(source['recommendation_types'][0]['definition'],result['recommendation_types'][0]['definition'],
                 'C.f','Custom','wrap-list',unannotated_target=True)
    source['recommendation_types'][0]['qualified_name']='unrelated.mod.C'
    with pytest.raises(Unsupported,match='unmasked_target_copy'):
        augment(source,'wrap-list')
    source['recommendation_types'][0]['qualified_name']='pkg.mod.C'
    source['recommendation_types'][0]['definition']='class C:\n    def f(self, y):\n        return opaque(y)\n'
    with pytest.raises(Unsupported,match='signature_mismatch'):
        augment(source,'wrap-list')


@pytest.mark.parametrize('op',['wrap-list','wrap-dict'])
def test_independent_ast_audit_checks_recursion_and_caller_adapters(op):
    from typepro.audit.contract_changing import compare_code
    source=row('def f(x) -> <mask>:\n    """old prose"""\n    if x:\n        return f(x-1)\n    return 1\ny=f(2)\n','int')
    result=augment(source,op)
    stats=compare_code(source['interprocedural_slice'],result['interprocedural_slice'],'f','int',op)
    assert stats['return_wrappers']==2 and stats['call_adapters']==2 and stats['removed_docstrings']==1
    tampered=result['interprocedural_slice'].replace('return [(1)]', 'return [(2)]').replace('return {"value": (1)}', 'return {"value": (2)}')
    assert tampered != result['interprocedural_slice']
    with pytest.raises(AssertionError):
        compare_code(source['interprocedural_slice'],tampered,'f','int',op)


@pytest.mark.parametrize('op',['wrap-list','wrap-dict'])
def test_unparenthesized_tuple_remains_one_return_value(op):
    source=row('def f() -> <mask>:\n    return 1, 2\n','Tuple[int, int]')
    result=augment(source,op)
    value=execute(result['interprocedural_slice'])['f']()
    assert value==([(1,2)] if op=='wrap-list' else {'value':(1,2)})
    from typepro.audit.contract_changing import compare_code
    compare_code(source['interprocedural_slice'],result['interprocedural_slice'],'f',source['label'],op)


def test_first_non_docstring_expression_is_not_removed():
    source=row('def f() -> <mask>:\n    f"{touch()}" "text"\n    return 1\n','int')
    result=augment(source,'wrap-list')
    events=[]
    scope=execute(result['interprocedural_slice'],dict(touch=lambda:events.append('called')))
    assert scope['f']()==[1] and events==['called']
    assert result['type_intervention']['stats']['docstrings']==0
