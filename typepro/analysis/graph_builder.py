"""Conservative per-function def-use graph with finite reaching-definition sets.

Unsupported effects are explicit gaps. Full enclosing scopes are retained for
these gaps by selection, rather than claiming Python's dynamic semantics closed.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from typepro.analysis.evidence_graph import EvidenceGraph, Node, Span, digest

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def functions(tree, prefix=''):
    """Qualified lexical identities; duplicate definitions remain distinct."""
    for node in tree.body:
        if isinstance(node, (*FUNCTIONS, ast.ClassDef)):
            name = f'{prefix}.{node.name}' if prefix else node.name
            if isinstance(node, FUNCTIONS):
                yield name, node
            yield from functions(node, name)


def structural_tree(source):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, FUNCTIONS):
            node.returns = None
            node.type_comment = None
        elif isinstance(node, ast.arg):
            node.annotation = None
            node.type_comment = None
        elif isinstance(node, ast.AnnAssign):
            node.annotation = ast.Constant(value=None)
        if hasattr(node, 'type_comment'):
            node.type_comment = None
    return tree


def join(*states):
    result = {}
    for state in states:
        for name, definitions in state.items():
            result.setdefault(name, set()).update(definitions)
    return result


class GraphBuilder:
    def __init__(self, source, file, scope, function, source_hash=None):
        self.file, self.scope, self.function = file, scope, function
        self.source_hash = source_hash or digest(ast.dump(structural_tree(source), include_attributes=False))
        self.graph = EvidenceGraph()
        self.calls = {}
        self.builtin_calls = {}
        self.parameters = {}
        self.returns = set()
        self.terminal_exits = set()
        self._keys = {}

    def node(self, node, kind, symbol=''):
        key = (self.scope, getattr(node, 'lineno', 0), getattr(node, 'col_offset', 0), kind, symbol)
        identifier = digest((self.file, key))
        if identifier not in self.graph.nodes:
            self.graph.nodes[identifier] = Node(identifier, kind, self.scope,
                Span(self.file, getattr(node, 'lineno', 0), getattr(node, 'end_lineno', 0), getattr(node, 'col_offset', 0)),
                self.source_hash, '\n'.join(ast.unparse(stmt) for stmt in node.body) if node is self.function and self.scope=='<module>' else ast.unparse(node), symbol)
        return identifier

    def container_kind(self,name,env):
        pending=list(env.get(name,()))
        seen=set()
        kinds=set()
        while pending:
            identifier=pending.pop()
            if identifier in seen:
                continue
            seen.add(identifier)
            node=self.graph.nodes[identifier]
            predecessors=[e.source for e in self.graph.edges if e.target==identifier and e.kind in {'assign','def_use','merge'}]
            if predecessors:
                pending.extend(predecessors)
                continue
            try:
                expression=ast.parse(node.text,mode='eval').body
            except (SyntaxError,ValueError):
                return None
            if isinstance(expression,(ast.List,ast.Tuple,ast.Dict,ast.Set)):
                kinds.add(type(expression).__name__)
            else:
                return None
        return next(iter(kinds)) if len(kinds)==1 else None

    def expr(self, node, env, controls=()):
        if node is None:
            return set()
        if isinstance(node, ast.Lambda):
            result = self.node(node, 'unresolved')
            self.graph.gap(result, 'lambda_scope_requires_summary')
            return {result}
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            result=self.node(node,'operation')
            outer_scope=self.scope
            local=dict((name,set(values)) for name,values in env.items())
            guards=list(controls)
            try:
                for index,generator in enumerate(node.generators):
                    if index==0:
                        inputs=self.expr(generator.iter,env,controls)
                    else:
                        inputs=self.expr(generator.iter,local,guards)
                    self.scope=f'{outer_scope}.<comprehension:{node.lineno}:{node.col_offset}>'
                    element=self.node(generator.target,'element',str(index))
                    for value in inputs:
                        self.graph.link(value,element,'element','comprehension_iterable_element')
                    self.bind(generator.target,{element},local,guards)
                    for condition in generator.ifs:
                        guards.extend(self.expr(condition,local,guards))
                    if generator.is_async:
                        self.graph.gap(result,'async_comprehension_dispatch_not_closed')
                values=[node.key,node.value] if isinstance(node,ast.DictComp) else [node.elt]
                for value in values:
                    for dependency in self.expr(value,local,guards):
                        self.graph.link(dependency,result,'element','comprehension_result_element')
                for guard in guards:
                    self.graph.link(guard,result,'control','comprehension_filter')
                if any(isinstance(child,ast.NamedExpr) for child in ast.walk(node)):
                    self.graph.gap(result,'comprehension_assignment_scope_not_closed')
            finally:
                self.scope=outer_scope
            return {result}
        kind = ('call' if isinstance(node, ast.Call) else 'field_read' if isinstance(node, ast.Attribute)
                else 'element' if isinstance(node, ast.Subscript) else 'yield' if isinstance(node, (ast.Yield, ast.YieldFrom))
                else 'await' if isinstance(node, ast.Await) else 'use' if isinstance(node, ast.Name) else 'operation')
        symbol = node.id if isinstance(node, ast.Name) else ''
        result = self.node(node, kind, symbol)
        for control in controls:
            self.graph.link(control, result, 'control', 'enclosing_control')
        if isinstance(node, ast.Name):
            definitions=env.get(node.id, ())
            if len(definitions)>1:
                merged=self.node(node,'merge',node.id)
                for definition in definitions:
                    self.graph.link(definition,merged,'merge','reaching_definition_join')
                self.graph.link(merged,result,'def_use','merged_reaching_definitions')
            else:
                for definition in definitions:
                    self.graph.link(definition, result, 'def_use', 'reaching_definition')
            return {result}
        if isinstance(node, ast.NamedExpr):
            values = self.expr(node.value, env, controls)
            self.bind(node.target, values, env, controls)
        else:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.expr):
                    for dependency in self.expr(child, env, controls):
                        edge = 'argument' if isinstance(node, ast.Call) and child is not node.func else 'def_use'
                        self.graph.link(dependency, result, 'yield' if kind == 'yield' else 'element' if kind == 'element' else 'field_read' if kind == 'field_read' else edge, 'expression_operand')
                elif isinstance(child, ast.keyword):
                    for dependency in self.expr(child.value, env, controls):
                        self.graph.link(dependency, result, 'argument', 'keyword_operand')
        if isinstance(node, ast.Call):
            self.calls[result] = node
            if isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and self.container_kind(node.func.value.id,env)=='List' and node.func.attr in {'append','extend'}:
                self.builtin_calls[result]='list.'+node.func.attr
            if isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name):
                for definition in env.get(node.func.value.id,()):
                    rule='may_container_mutation:'+node.func.attr if node.func.attr in {'append','extend'} else 'potential_receiver_mutation'
                    self.graph.link(result,definition,'field_write',rule)
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            self.returns.add(result)
        if isinstance(node,(ast.Attribute,ast.Subscript)):
            receiver=node.value
            known=self.container_kind(receiver.id,env) if isinstance(receiver,ast.Name) else None
            known_method=isinstance(node,ast.Attribute) and known=='List' and node.attr in {'append','extend'}
            if not known_method and not (isinstance(node,ast.Subscript) and known in {'List','Tuple','Dict'}):
                self.graph.gap(result,'receiver_or_element_identity_not_proven')
        return {result}

    def bind(self, target, values, env, controls=()):
        if isinstance(target, (ast.Tuple, ast.List)):
            for index,element in enumerate(target.elts):
                projected=self.node(element,'element',str(index))
                for value in values:
                    self.graph.link(value,projected,'unpack','positional_unpack:'+str(index))
                self.bind(element,{projected},env,controls)
            return
        if isinstance(target,ast.Starred):
            self.graph.gap(self.node(target,'unresolved'),'starred_unpack_cardinality_not_closed')
            self.bind(target.value,values,env,controls)
            return
        kind = 'binding' if isinstance(target, ast.Name) else 'field_write'
        name = target.id if isinstance(target, ast.Name) else ast.unparse(target)
        binding = self.node(target, kind, name)
        for value in values:
            self.graph.link(value, binding, 'assign', 'assignment')
        for control in controls:
            self.graph.link(control, binding, 'control', 'enclosing_control')
        if isinstance(target, ast.Name):
            for value in values:
                if self.graph.nodes[value].kind=='use':
                    originals={edge.source for edge in self.graph.edges if edge.target==value and edge.kind=='def_use'}
                    for original in originals:
                        self.graph.link(binding,original,'alias','assignment_reference_may_alias')
            env[name] = {binding}
        else:
            self.expr(target, env, controls)
            self.graph.gap(binding, 'mutation_alias_identity_not_proven')

    def block(self, statements, env, controls=()):
        env = deepcopy(env)
        live = True
        for stmt in statements:
            if not live:
                break
            if isinstance(stmt, ast.Assign):
                values = self.expr(stmt.value, env, controls)
                for target in stmt.targets:
                    self.bind(target, values, env, controls)
            elif isinstance(stmt, ast.AnnAssign):
                self.bind(stmt.target, self.expr(stmt.value, env, controls), env, controls)
            elif isinstance(stmt, ast.AugAssign):
                values = self.expr(stmt.target, env, controls) | self.expr(stmt.value, env, controls)
                self.bind(stmt.target, values, env, controls)
            elif isinstance(stmt, (ast.Return, ast.Raise)):
                result = self.node(stmt, 'return' if isinstance(stmt, ast.Return) else 'raise')
                for dependency in self.expr(getattr(stmt, 'value', None) or getattr(stmt, 'exc', None), env, controls):
                    self.graph.link(dependency, result, 'return', 'explicit_exit')
                for control in controls:
                    self.graph.link(control, result, 'control', 'enclosing_control')
                if isinstance(stmt, ast.Return):
                    self.returns.add(result)
                else:
                    self.terminal_exits.add(result)
                live = False
            elif isinstance(stmt, ast.If):
                conditions = self.expr(stmt.test, env, controls)
                yes, yes_live = self.block(stmt.body, env, (*controls, *conditions))
                no, no_live = self.block(stmt.orelse, env, (*controls, *conditions))
                env = join(*(s for s, alive in ((yes, yes_live), (no, no_live)) if alive))
                live = yes_live or no_live
            elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
                marker = self.node(stmt.test if isinstance(stmt,ast.While) else stmt.iter, 'condition')
                initial = deepcopy(env)
                # Nodes are keyed by source site. Sets grow monotonically; the
                # finite set of sites bounds this fixed point without guessing.
                while True:
                    previous = deepcopy(env)
                    values = self.expr(stmt.test if isinstance(stmt, ast.While) else stmt.iter, env, controls)
                    for value in values:
                        self.graph.link(value, marker, 'control', 'loop_condition')
                    if not isinstance(stmt, ast.While):
                        element=self.node(stmt.target,'element','iteration')
                        for value in values:
                            self.graph.link(value,element,'element','loop_iterable_element')
                        self.bind(stmt.target,{element},env,(*controls,marker))
                    body, _ = self.block(stmt.body, env, (*controls, marker))
                    env = join(initial, env, body)
                    if env == previous:
                        break
                env, _ = self.block(stmt.orelse, env, (*controls, marker))
                if any(isinstance(n,(ast.Break,ast.Continue)) for body in stmt.body for n in ast.walk(body)):
                    self.graph.gap(marker,'loop_break_continue_exit_overapproximation')
                elif isinstance(stmt,ast.While):
                    self.graph.gap(marker,'loop_termination_not_proven')
            elif isinstance(stmt, (ast.Try, getattr(ast, 'TryStar', ast.Try))):
                marker = self.node(stmt, 'unresolved')
                self.graph.gap(marker, 'exception_and_finally_exit_overapproximation')
                body, _ = self.block(stmt.body, env, controls)
                branches = [body, env]
                for handler in stmt.handlers:
                    branch = join(env, body)
                    if handler.name:
                        branch[handler.name] = {marker}
                    branch, _ = self.block(handler.body, branch, controls)
                    branches.append(branch)
                otherwise, _ = self.block(stmt.orelse, body, controls)
                env, _ = self.block(stmt.finalbody, join(*branches, otherwise), controls)
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                for item in stmt.items:
                    values = self.expr(item.context_expr, env, controls)
                    if item.optional_vars:
                        self.bind(item.optional_vars, values, env, controls)
                env, live = self.block(stmt.body, env, controls)
                self.graph.gap(self.node(stmt, 'unresolved'), 'context_manager_exit_effect')
            elif isinstance(stmt, (*FUNCTIONS, ast.ClassDef)):
                binding = self.node(stmt, 'binding', stmt.name)
                env[stmt.name] = {binding}
                self.graph.gap(binding, 'nested_scope_or_closure_requires_summary')
            elif isinstance(stmt, (ast.Break, ast.Continue)):
                self.graph.gap(self.node(stmt, 'unresolved'), 'loop_exit')
                live = False
            elif isinstance(stmt, ast.Expr):
                self.expr(stmt.value, env, controls)
            elif isinstance(stmt, (ast.Pass,)):
                pass
            else:
                marker = self.node(stmt, 'unresolved')
                self.graph.gap(marker, f'unsupported_statement:{type(stmt).__name__}')
                for child in ast.iter_child_nodes(stmt):
                    if isinstance(child, ast.expr):
                        self.expr(child, env, controls)
        return env, live

    def build(self, target):
        args = self.function.args
        parameters = args.posonlyargs + args.args + args.kwonlyargs + [p for p in (args.vararg, args.kwarg) if p]
        env = {}
        for parameter in parameters:
            identifier = self.node(parameter, 'parameter', parameter.arg)
            self.parameters[parameter.arg] = identifier
            env[parameter.arg] = {identifier}
        positional=args.posonlyargs+args.args
        defaults=list(zip(positional[len(positional)-len(args.defaults):],args.defaults))
        defaults += [(a,d) for a,d in zip(args.kwonlyargs,args.kw_defaults) if d is not None]
        for parameter,default in defaults:
            for value in self.expr(default,{}):
                self.graph.link(value,self.parameters[parameter.arg],'argument','source_parameter_default')
        _, live = self.block(self.function.body, env)
        if live:
            implicit = self.node(self.function, 'implicit_none')
            self.returns.add(implicit)
        if target.scope == 'return':
            self.graph.seeds.update(self.returns or self.terminal_exits or {self.node(self.function,'no_return')})
        else:
            if target.name not in self.parameters:
                raise LookupError('Target parameter not found')
            self.graph.seeds.add(self.parameters[target.name])
            # Reassignments and all uses of the target parameter stay visible.
            self.graph.seeds.update(n.id for n in self.graph.nodes.values() if n.symbol == target.name and n.scope==self.scope)
        return self.graph
