import ast
from dataclasses import asdict
import json

import pytest

from typepro.analysis.evidence_graph import TargetSpec
from typepro.analysis.graph_builder import GraphBuilder, structural_tree
from typepro.analysis.graph_context import GraphContextProject
from typepro.analysis.graph_resolver import bind_arguments
from typepro.analysis.graph_selection import EvidenceGroup
from typepro.shared.context_packing import BudgetExceeded, pack_groups, prompt_token_ids, training_token_ids, tokenizer_fingerprint
from typepro.shared.generative_chat import left_pad_causal_batch


class Tokenizer:
    chat_template = 'synthetic-template-v1'
    special_tokens_map = {'eos_token': '<eos>'}
    init_kwargs = {'_commit_hash': 'fixed'}

    def apply_chat_template(self, messages, tokenize=True, add_generation_prompt=False):
        ids = [1]
        for message in messages:
            ids += [2 if message['role'] == 'system' else 3 if message['role'] == 'user' else 4]
            ids += [ord(c) + 10 for c in message['content']]
            ids += [5]
        if add_generation_prompt:
            ids += [4]
        return ids


def query(source, scope='return', name='f', **kwargs):
    project = GraphContextProject('owner/repo', {'m.py': source}, 'locked-source', 'locked-kb')
    target = TargetSpec('owner/repo', 'm.py', 'f', scope, name)
    return project.query(target, Tokenizer(), input_length=20000, **kwargs)


def build(source, scope='return', name='f'):
    tree = structural_tree(source)
    builder = GraphBuilder(source, 'm.py', 'f', tree.body[0])
    return builder.build(TargetSpec('p', 'm.py', 'f', scope, name))


def ancestors(graph, identifier):
    result = {identifier}
    while True:
        new = result | {e.source for e in graph.edges if e.target in result}
        if new == result:
            return result
        result = new


def test_reassignment_uses_only_latest_binding():
    graph = build('def f():\n x = 1\n x = "new"\n return x\n')
    result = next(n for n in graph.nodes.values() if n.kind == 'return')
    bindings = [graph.nodes[k] for k in ancestors(graph, result.id) if graph.nodes[k].kind == 'binding']
    assert [b.span.start for b in bindings] == [3]


def test_branch_join_retains_both_definitions_and_control():
    graph = build('def f(flag):\n if flag:\n  x = 1\n else:\n  x = "s"\n return x\n')
    result = next(n for n in graph.nodes.values() if n.kind == 'return')
    kept = [graph.nodes[k] for k in ancestors(graph, result.id)]
    assert {n.span.start for n in kept if n.kind == 'binding'} == {3, 5}
    assert any(n.kind == 'parameter' and n.symbol == 'flag' for n in kept)


def test_loop_fixed_point_keeps_initial_and_carried_definitions():
    graph = build('def f(xs):\n x = 0\n for y in xs:\n  x = x + y\n return x\n')
    result = next(n for n in graph.nodes.values() if n.kind == 'return')
    kept = [graph.nodes[k] for k in ancestors(graph, result.id)]
    assert {n.span.start for n in kept if n.kind == 'binding' and n.symbol == 'x'} == {2, 4}
    assert any(e.rule=='loop_iterable_element' for e in graph.edges)


def test_early_return_has_no_false_implicit_none():
    graph = build('def f(flag):\n if flag:\n  return 1\n else:\n  return "x"\n')
    assert not any(n.kind == 'implicit_none' for n in graph.nodes.values())
    assert len(graph.seeds) == 2


def test_implicit_none_path_is_seeded():
    graph = build('def f(flag):\n if flag:\n  return 1\n')
    assert any(graph.nodes[k].kind == 'implicit_none' for k in graph.seeds)


def test_finally_mutation_nested_scope_and_comprehension_remain_explicit():
    source = '''def f(xs):
 x = []
 y = x
 def g():
  x = "other"
  return x
 try:
  y.append(1)
  return [x for x in xs]
 finally:
  return x
'''
    result = query(source)
    assert result['outcome'] == 'unresolved'
    assert 'finally' in result['input'] and 'def g' in result['input']
    reasons = [g['reason'] for g in result['gaps']]
    assert 'exception_and_finally_exit_overapproximation' in reasons
    assert 'nested_scope_or_closure_requires_summary' in reasons
    assert any('<comprehension:' in n['scope'] for n in result['audit']['graph']['nodes'])
    graph = result['audit']['graph']
    assert not any(n['kind'] == 'binding' and n['text'] == 'x' and n['span']['start'] == 5 for n in graph['nodes'])


@pytest.mark.parametrize('scope,name', [('return','f'), ('arg','x')])
def test_target_annotation_invariant_cold_warm_and_order(scope, name):
    outputs = []
    for annotation in ('SecretGold', 'list[DifferentGold]', '"Unicode秘密"'):
        source = f'def f(x: {annotation}) -> {annotation}:\n return x\n'
        if scope == 'arg':
            source = f'def f(x: {annotation}) -> object:\n return x\n'
        else:
            source = f'def f(x: object) -> {annotation}:\n return x\n'
        project = GraphContextProject('p', {'m.py': source}, 'sha', 'kb')
        spec = TargetSpec('p', 'm.py', 'f', scope, name)
        first = project.query(spec, Tokenizer(), 20000)
        project.query(TargetSpec('p', 'm.py', 'f', 'arg' if scope == 'return' else 'return', 'x' if scope == 'return' else 'f'), Tokenizer(), 20000)
        second = project.query(spec, Tokenizer(), 20000)
        assert first['input'] == second['input']
        assert first['cache_key'] == second['cache_key']
        assert 'Gold' not in first['input'] and '秘密' not in first['input']
        outputs.append((first['input'], first['audit']['retained_groups'], first['cache_key']))
    assert outputs[0] == outputs[1] == outputs[2]


def test_calls_have_verified_rules_and_callsite_separate_formals():
    source = '''def helper(a, *, b=1):
 return a

def f(x):
 a = helper(x, b=2)
 b = helper("other")
 return a, b
'''
    result = query(source)
    graph = result['audit']['graph']
    formal_nodes = [n for n in graph['nodes'] if n['kind'] == 'parameter' and n['symbol'] == 'a']
    assert len(formal_nodes) == 2
    assert len({n['scope'] for n in formal_nodes}) == 2
    assert any(e['rule'] == 'lexical_definition:formal_binding' for e in graph['edges'])
    assert all(e['rule'] for e in graph['edges'])


def test_binding_keywords_defaults_posonly_and_expansions():
    function = ast.parse('def f(a, /, b=2, *, c=3): pass').body[0]
    call = lambda text: ast.parse(text, mode='eval').body
    assert [(ast.unparse(a), b) for a,b in bind_arguments(call('f(1, c=4)'), function)] == [('1','a'), ('4','c'), ('2','b')]
    assert bind_arguments(call('f(a=1)'), function) is None
    assert bind_arguments(call('f(*xs)'), function) is None
    assert bind_arguments(call('f(1, **kw)'), function) is None


def test_shadowed_builtin_is_not_certified():
    result = query('def f(map, xs):\n return map(str, xs)\n')
    assert result['outcome'] == 'unresolved'
    assert not any(e['rule'].startswith('builtin:map') for e in result['audit']['graph']['edges'])


def test_recursive_and_dynamic_calls_report_gaps_and_keep_scope():
    recursive = query('def f(x):\n return f(x)\n')
    assert any(g['reason'] == 'recursive_summary_not_closed' for g in recursive['gaps'])
    dynamic = query('def f(obj):\n return obj.method()\n')
    assert dynamic['outcome'] == 'unresolved'
    assert 'obj.method()' in dynamic['input']


def test_missing_and_parse_outcomes():
    project = GraphContextProject('p', {'m.py':'invalid python!'}, 'sha', 'kb')
    assert project.query(TargetSpec('p','m.py','f','return','f'), Tokenizer())['outcome'] == 'parse_error'
    project = GraphContextProject('p', {'m.py':'x=1'}, 'sha', 'kb')
    assert project.query(TargetSpec('p','m.py','f','return','f'), Tokenizer())['outcome'] == 'target_not_found'


def test_budget_exceeded_keeps_full_mandatory_evidence():
    project = GraphContextProject('p', {'m.py':'def f():\n return "' + 'a'*1000 + '"'}, 'sha', 'kb')
    result = project.query(TargetSpec('p','m.py','f','return','f'), Tokenizer(), 500, 64)
    assert result['outcome'] == 'budget_exceeded' and result['input'] is None
    assert result['audit']['mandatory_tokens'] > 436
    assert 'a'*1000 in result['full_evidence'][0]['text']


def test_packing_prerequisites_and_exact_final_template_cost():
    tokenizer = Tokenizer()
    groups = [EvidenceGroup('header','m',1,1,'H',mandatory=True),
              EvidenceGroup('owner','m',2,2,'OWNER'),
              EvidenceGroup('field','m',3,3,'FIELD',prerequisites=('owner',)),
              EvidenceGroup('noise','m',4,4,'X'*500)]
    render = lambda gs: '|'.join(g.text for g in sorted(gs,key=lambda g:g.id))
    packed = pack_groups(tokenizer, groups, render, 400, 64)
    assert {'header','owner','field'} <= set(packed.retained)
    assert packed.omitted == {'noise':'marginal_token_budget'}
    assert len(packed.prompt_ids) <= 336


def test_chat_boundary_completion_eos_labels_unicode_and_batching():
    tokenizer = Tokenizer()
    prompt, sequence = training_token_ids(tokenizer, '秘密 unicode', 'list[str]', 1000, 64)
    assert prompt == prompt_token_ids(tokenizer, '秘密 unicode', 1000, 64)
    assert prompt[-1] == 4 and sequence[-1] == 5
    assert sequence[:len(prompt)] == prompt
    p2, s2 = training_token_ids(tokenizer, 'short', 'str', 1000, 64)
    batch = left_pad_causal_batch([prompt,p2], [sequence,s2], 0)
    for labels, mask, seq, p in zip(batch['labels'], batch['attention_mask'], [sequence,s2], [prompt,p2]):
        active = labels[mask.bool()].tolist()
        assert active[:len(p)] == [-100]*len(p)
        assert active[len(p):] == seq[len(p):]
    with pytest.raises(BudgetExceeded):
        prompt_token_ids(tokenizer, 'x'*1000, 400, 64)
    with pytest.raises(ValueError, match='Completion requires'):
        training_token_ids(tokenizer, 'x', 'list[str]', 1000, 2)
    before = tokenizer_fingerprint(tokenizer)
    tokenizer.chat_template = 'changed'
    assert tokenizer_fingerprint(tokenizer) != before


def test_selection_removes_unrelated_straight_line_statement():
    result = query('def f(x):\n unused = 42\n return x\n')
    assert 'unused' not in result['input']
    assert 'return x' in result['input']


def test_alias_cycle_and_owner_support_have_provenance_and_prerequisites():
    source = 'A = B\nB = A\ndef f():\n return A\n'
    result = query(source)
    assert any(g['reason']=='alias_cycle' for g in result['gaps'])
    source = '''class Owner:
 field: int
 unrelated: str
 def __init__(self, x):
  self.field = x
 def f(self):
  return self.field
'''
    project = GraphContextProject('p',{'m.py':source},'sha','kb')
    result = project.query(TargetSpec('p','m.py','Owner.f','return','f'),Tokenizer(),20000)
    assert 'field: int' in result['input']
    assert 'unrelated: str' not in result['input']
    assert any(g['prerequisites'] for g in result['full_evidence'])


def test_fixture_scope_explicit_name_and_override():
    sources = {'conftest.py':'import pytest\n@pytest.fixture(name="resource")\ndef root():\n return "root"\n',
               'tests/conftest.py':'import pytest\n@pytest.fixture(name="resource")\ndef local():\n return 1\n',
               'unrelated/conftest.py':'import pytest\n@pytest.fixture\ndef resource():\n return "wrong"\n',
               'tests/test_m.py':'def test_feature(resource: int):\n assert resource\n'}
    project=GraphContextProject('p',sources,'sha','kb')
    result=project.query(TargetSpec('p','tests/test_m.py','test_feature','arg','resource'),Tokenizer(),20000)
    assert 'def local' in result['input']
    assert 'def root' not in result['input'] and 'wrong' not in result['input']
    assert any(e['rule']=='pytest_scoped_fixture:resource' for e in result['audit']['graph']['edges'])


def test_structural_summary_cache_is_target_independent():
    project=GraphContextProject('p',{'m.py':'def f(x: int) -> str:\n return x\n'},'sha','kb')
    first=project.query(TargetSpec('p','m.py','f','return','f'),Tokenizer(),20000)
    second=project.query(TargetSpec('p','m.py','f','arg','x'),Tokenizer(),20000)
    third=project.query(TargetSpec('p','m.py','f','return','f'),Tokenizer(),20000)
    assert first['input']==third['input']
    assert second['audit']['structural_cache_hits']>first['audit']['structural_cache_hits']
    assert all(not b.graph.seeds for b in project._summaries.values())
    assert all(n.returns is None for n in project.resolver.trees['m.py'].body if isinstance(n,ast.FunctionDef))


def test_ambiguous_definitions_require_explicit_occurrence():
    project=GraphContextProject('p',{'m.py':'def f(): return 1\ndef f(): return "s"\n'},'sha','kb')
    assert project.query(TargetSpec('p','m.py','f','return','f'),Tokenizer(),20000)['outcome']=='target_not_found'
    result=project.query(TargetSpec('p','m.py','f','return','f',1),Tokenizer(),20000)
    assert "return 's'" in result['input']


def test_scc_summaries_reach_fixed_point_for_mutual_recursion():
    from typepro.analysis.graph_summaries import summarize
    from typepro.analysis.graph_resolver import GraphResolver
    resolver=GraphResolver({'m.py':'def f(x):\n return g(x)\ndef g(x):\n return f(x)\n'})
    summaries=summarize(resolver)
    f=summaries[('m.py','f',0)]
    g=summaries[('m.py','g',0)]
    assert f['recursive'] and g['recursive']
    assert f['return_sites']==g['return_sites']==[('m.py','f',2),('m.py','g',4)]
    assert f['component']==[('m.py','f',0),('m.py','g',0)]


def test_class_namespace_is_not_a_method_lexical_scope():
    source='class C:\n def helper(self): return 1\n def f(self): return helper()\n'
    project=GraphContextProject('p',{'m.py':source},'sha','kb')
    result=project.query(TargetSpec('p','m.py','C.f','return','f'),Tokenizer(),20000)
    assert not any(e['rule']=='lexical_definition:return_summary' for e in result['audit']['graph']['edges'])
    assert result['outcome']=='unresolved'


def test_explicit_annotation_conflicts_keep_both_declarations():
    from typepro.analysis.graph_conflicts import annotation_conflicts
    groups=[EvidenceGroup('a','m.py',1,1,'field: int',owner='Owner'),
            EvidenceGroup('b','m.py',2,2,'field: str',owner='Owner')]
    conflicts=annotation_conflicts(groups)
    assert len(conflicts)==1
    assert {v['annotation'] for v in conflicts[0]['declarations']}=={'int','str'}


def test_unresolved_nodes_in_instantiated_callee_are_valid():
    result=query('def g(x):\n return x.attribute\ndef f(x):\n return g(x)\n')
    graph=result['audit']['graph']; nodes={n['id'] for n in graph['nodes']}
    assert all(g['node'] in nodes and g['unresolved_node'] in nodes for g in graph['gaps'])


def test_docstrings_survive_graph_statement_selection():
    source='def f(x):\n """Keep this source documentation for the model."""\n unrelated = 42\n return x\n'
    result=query(source)
    assert 'Keep this source documentation for the model.' in result['input']
    assert 'unrelated' not in result['input']


def test_verified_callers_retain_actual_argument_evidence():
    result=query('def f(value: object):\n return value\ndef caller():\n return f({"name": "example"})\n',scope='arg',name='value')
    assert 'def caller' in result['input']
    assert "'name': 'example'" in result['input']
    assert any(e['rule']=='lexical_definition:verified_caller_binding' for e in result['audit']['graph']['edges'])


def test_module_callers_keep_source_without_synthetic_function_wrapper():
    result=query('def f(value: object):\n return value\nf([1, 2])\n',scope='arg',name='value')
    assert 'f([1, 2])' in result['input']
    assert '__typepro_module_evidence__' not in result['input']


def test_raise_only_target_has_an_exit_seed():
    result=query('def f():\n raise ValueError("no return")\n')
    assert result['audit']['graph']['seeds']
    assert 'raise ValueError' in result['input']


def test_reexport_and_local_import_resolve_exact_source_definition():
    sources={'pkg/implementation.py':'def helper(value):\n return value\n',
             'pkg/__init__.py':'from .implementation import helper as public\n',
             'm.py':'from pkg import public\ndef f(value):\n return public(value)\n'}
    project=GraphContextProject('p',sources,'sha','kb')
    result=project.query(TargetSpec('p','m.py','f','return','f'),Tokenizer(),20000)
    assert 'def helper(value)' in result['input']
    assert any(e['rule']=='exact_import_or_reexport:return_summary' for e in result['audit']['graph']['edges'])
    sources['m.py']='def f(value):\n from pkg import public\n return public(value)\n'
    result=GraphContextProject('p',sources,'sha','kb').query(TargetSpec('p','m.py','f','return','f'),Tokenizer(),20000)
    assert 'def helper(value)' in result['input']


def test_reexport_cycle_is_explicit_and_does_not_recurse_forever():
    sources={'a.py':'from b import missing\n','b.py':'from a import missing\n',
             'm.py':'from a import missing\ndef f():\n return missing()\n'}
    result=GraphContextProject('p',sources,'sha','kb').query(TargetSpec('p','m.py','f','return','f'),Tokenizer(),20000)
    assert result['outcome']=='unresolved'


def test_bound_instance_method_preserves_self_binding():
    source='class C:\n def helper(self, x):\n  return x\n def f(self, x):\n  return self.helper(x)\n'
    result=GraphContextProject('p',{'m.py':source},'sha','kb').query(TargetSpec('p','m.py','C.f','return','f'),Tokenizer(),20000)
    assert 'def helper(self, x)' in result['input']
    assert not any(g['reason']=='argument_binding_unresolved' for g in result['gaps'])
    assert any(e['rule']=='receiver_member:formal_binding' for e in result['audit']['graph']['edges'])


def test_base_property_keeps_owner_getter_field_and_constructor():
    sources={'base.py':'class Base:\n _value: str\n def __init__(self, value):\n  self._value = value\n @property\n def value(self):\n  return self._value\n',
             'm.py':'from base import Base\nclass Child(Base):\n unrelated: bytes\n def f(self):\n  return self.value\n'}
    result=GraphContextProject('p',sources,'sha','kb').query(TargetSpec('p','m.py','Child.f','return','f'),Tokenizer(),20000)
    assert 'class Base' in result['input'] and 'def value(self)' in result['input']
    assert '_value: str' in result['input'] and 'self._value = value' in result['input']
    assert 'unrelated: bytes' not in result['input']
    assert any(g['reason']=='inheritance_dispatch_not_closed' for g in result['gaps'])


def test_module_noise_is_not_packed_without_a_target_dependency_path():
    source='UNRELATED = "noise"\ndef f(x):\n return x\n'
    result=query(source)
    assert 'UNRELATED' not in result['input']


def test_map_callback_has_element_and_formal_provenance():
    result=query('def callback(item):\n return str(item)\ndef f(values):\n return map(callback, values)\n')
    assert 'def callback(item)' in result['input']
    edges=result['audit']['graph']['edges']
    assert any(e['rule']=='builtin_map_callback_formal' for e in edges)
    assert any(e['rule']=='builtin_map_result_element' for e in edges)
    assert not any(g['reason']=='callback_summary_not_closed' for g in result['gaps'])


def test_unknown_wildcard_cannot_certify_a_builtin_contract():
    result=query('from unavailable_module import *\ndef f(xs):\n return map(str, xs)\n')
    assert result['outcome']=='unresolved'
    assert not any(e['rule'].startswith('graph-builtin-contracts-v1:map') for e in result['audit']['graph']['edges'])


def test_comprehension_shadowing_has_distinct_bindings():
    result=query('def f(x):\n unrelated = [x for x in [1, 2]]\n return x\n',scope='arg',name='x')
    assert 'unrelated' not in result['input']
    nodes=result['audit']['graph']['nodes']
    assert any(n['symbol']=='x' and '<comprehension:' in n['scope'] for n in nodes)
    seeds=set(result['audit']['graph']['seeds'])
    assert not any(n['id'] in seeds and '<comprehension:' in n['scope'] for n in nodes)


def test_fixture_dependencies_and_explicit_plugins_keep_source_provenance():
    sources={'tests/test_m.py':'def test_feature(resource):\n assert resource\n',
             'tests/conftest.py':'import pytest\npytest_plugins = ["fixtures.plugin"]\n@pytest.fixture\ndef resource(connection):\n return connection\n',
             'fixtures/plugin.py':'import pytest\n@pytest.fixture\ndef connection():\n return "connected"\n'}
    result=GraphContextProject('p',sources,'sha','kb').query(TargetSpec('p','tests/test_m.py','test_feature','arg','resource'),Tokenizer(),20000)
    assert 'def resource(connection)' in result['input'] and 'def connection()' in result['input']
    assert 'fixtures/plugin.py' in result['input']
    assert not any(g['reason']=='pytest_fixture_binding_unresolved' for g in result['gaps'])


def test_module_rebinding_does_not_create_a_verified_callable_edge():
    source='def helper(x): return x\nhelper = obtain_callable()\ndef f(x): return helper(x)\n'
    result=query(source)
    assert result['outcome']=='unresolved'
    assert not any(e['rule']=='lexical_definition:return_summary' for e in result['audit']['graph']['edges'])


def test_source_parameter_default_is_connected_to_argument_seed():
    result=query('def f(value=None):\n return value\n',scope='arg',name='value')
    assert any(e['rule']=='source_parameter_default' for e in result['audit']['graph']['edges'])


def test_unpack_alias_hypothesis_is_optional_and_never_resolves_fixture():
    source='from typing import Tuple\nPayload = Tuple[str, int]\ndef f(bundle):\n text, count = bundle\n return text\n'
    result=query(source,scope='arg',name='bundle')
    assert 'Payload = Tuple[str, int]' in result['input']
    groups=[g for g in result['full_evidence'] if 'Payload =' in g['text']]
    assert groups and all(not g['mandatory'] and g['priority']==4 for g in groups)
    assert any(e['kind']=='hypothesis' for e in result['audit']['graph']['edges'])


def test_callee_inplace_mutation_keeps_caller_and_element_evidence():
    result=query('def fill(items):\n items += ["text"]\ndef f():\n items = []\n fill(items)\n return items\n')
    assert 'fill(items)' in result['input']
    assert "items += ['text']" in result['input']
    assert result['outcome']=='unresolved'
    assert any(g['reason']=='inplace_argument_alias_effect_not_closed' for g in result['gaps'])


@pytest.mark.parametrize('sources',[
    {'m.py':'def f(key):\n from external import fetch\n return fetch(key)\n'},
    {'m.py':'from external import fetch\ndef helper(key):\n return fetch(key)\ndef f(key):\n return helper(key)\n'},
    {'m.py':'from helper import run\ndef f(key):\n return run(key)\n',
     'helper.py':'from external import fetch\ndef run(key):\n return fetch(key)\n'},
])
def test_frozen_dependency_support_covers_local_imports_and_reached_helpers(sources):
    kb={'records':[{'qualified_name':'external.fetch','definition':'def fetch(key: str) -> bytes: ...','source_file':'external.py'}]}
    result=GraphContextProject('p',sources,'sha','kb',dependency_kb=kb).query(
        TargetSpec('p','m.py','f','return','f'),Tokenizer(),20000)
    assert 'def fetch(key: str) -> bytes' in result['input']


def test_shadowed_import_does_not_pull_unrelated_dependency_definition():
    source='from external import fetch\ndef f(fetch):\n return fetch("key")\n'
    kb={'records':[{'qualified_name':'external.fetch','definition':'def fetch(key: str) -> bytes: ...'}]}
    result=GraphContextProject('p',{'m.py':source},'sha','kb',dependency_kb=kb).query(
        TargetSpec('p','m.py','f','return','f'),Tokenizer(),20000)
    assert 'def fetch(key: str)' not in result['input']


def test_frozen_dependency_keeps_non_target_signature_support():
    source='from external import User\ndef f(value: User):\n return value\n'
    kb={'records':[{'qualified_name':'external.User','definition':'class User:\n name: str'}]}
    result=GraphContextProject('p',{'m.py':source},'sha','kb',dependency_kb=kb).query(
        TargetSpec('p','m.py','f','return','f'),Tokenizer(),20000)
    assert 'class User:' in result['input']
