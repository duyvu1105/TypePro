"""One graph -> resolve -> select -> render -> pack path for every target."""
from __future__ import annotations
import ast
from collections import OrderedDict
from copy import copy, deepcopy
from dataclasses import replace
from dataclasses import asdict
import time
from typepro.analysis.evidence_graph import POLICY, SCHEMA, MASKING, TargetSpec, Node, Span, digest
from typepro.analysis.graph_builder import GraphBuilder, functions
from typepro.analysis.graph_resolver import GraphResolver, bind_arguments
from typepro.analysis.graph_contracts import VERSION as CONTRACT_VERSION
from typepro.analysis.graph_selection import EvidenceGroup, dependency_closure, canonicalize_groups
from typepro.analysis.graph_render import render_groups, render_function_excerpt
from typepro.analysis.target_context import MaskedSources
from typepro.shared.context_packing import pack_groups, tokenizer_fingerprint, VERSION as BUDGET_POLICY


class GraphContextProject:
    """One source catalog per project; target overlays never enter shared caches.

    Source snapshots are immutable by convention. The retained structural catalog
    erases every annotation before indexing, independent of target query order.
    """
    def __init__(self, project, sources, source_commit, dependency_hash, max_expansions=32, dependency_kb=None, module_aliases=None):
        if not source_commit or not dependency_hash or max_expansions < 1:
            raise ValueError('Require source/dependency locks and positive expansion bound')
        self.project = project
        self.sources = dict(sources)
        self.source_commit = source_commit
        self.dependency_hash = dependency_hash
        self.max_expansions = max_expansions
        self.dependency_kb = dependency_kb or {}
        started = time.monotonic()
        self.resolver = GraphResolver(sources,module_aliases)
        self.build_seconds = time.monotonic() - started
        self.source_hash = digest(self.sources)
        self.file_hashes = {f: digest(ast.dump(t, include_attributes=False)) for f, t in self.resolver.trees.items()}
        self.structural_hash = digest(self.file_hashes)
        self._summaries = OrderedDict()
        self._recursive_summaries = None
        self._summary_nodes = 0
        self._summary_bytes = 0
        self.cache_hits = 0
        self.cache_misses = 0

    def _builder(self, definition, suffix=''):
        if definition.key in self._summaries:
            self.cache_hits += 1
            self._summaries.move_to_end(definition.key)
            template = self._summaries[definition.key]
        else:
            self.cache_misses += 1
            template = GraphBuilder('', definition.file, definition.qualified, definition.node,
                                    self.file_hashes[definition.file])
            template.build(TargetSpec(self.project, definition.file, definition.qualified, 'return', definition.node.name, definition.occurrence))
            template.graph.seeds.clear()
            template.accounted_bytes=sum(len(n.text.encode('utf-8'))+256 for n in template.graph.nodes.values())+128*len(template.graph.edges)
            while self._summaries and (len(self._summaries) >= 64 or self._summary_nodes + len(template.graph.nodes) > 100000
                                       or self._summary_bytes+template.accounted_bytes>64*1024*1024):
                _, old = self._summaries.popitem(last=False)
                self._summary_nodes -= len(old.graph.nodes)
                self._summary_bytes -= old.accounted_bytes
            if len(template.graph.nodes) <= 100000 and template.accounted_bytes<=64*1024*1024:
                self._summaries[definition.key] = template
                self._summary_nodes += len(template.graph.nodes)
                self._summary_bytes += template.accounted_bytes
        builder = copy(template)
        builder.graph = deepcopy(template.graph)
        builder.calls = dict(template.calls)
        builder.builtin_calls = dict(template.builtin_calls)
        builder.parameters = dict(template.parameters)
        builder.returns = set(template.returns)
        builder.terminal_exits = set(template.terminal_exits)
        if suffix:
            mapping = {k: digest((k, suffix)) for k in builder.graph.nodes}
            builder.scope += '@' + suffix
            builder.graph.nodes = {mapping[k]: replace(n, id=mapping[k], scope=n.scope+'@'+suffix) for k,n in builder.graph.nodes.items()}
            builder.graph.edges = {replace(e, source=mapping[e.source], target=mapping[e.target]) for e in builder.graph.edges}
            builder.graph.gaps = [dict(g, node=mapping[g['node']], unresolved_node=mapping[g['unresolved_node']]) for g in builder.graph.gaps]
            builder.calls = {mapping[k]: v for k,v in builder.calls.items()}
            builder.builtin_calls = {mapping[k]:v for k,v in builder.builtin_calls.items()}
            builder.parameters = {k: mapping[v] for k,v in builder.parameters.items()}
            builder.returns = {mapping[k] for k in builder.returns}
            builder.terminal_exits = {mapping[k] for k in builder.terminal_exits}
        return builder

    def query(self, target, tokenizer, input_length=6144, label_length=64):
        started = time.monotonic()
        if target.project != self.project:
            raise ValueError('Target belongs to another project')
        fingerprint = tokenizer_fingerprint(tokenizer)
        base = dict(target=asdict(target), target_id=target.identity,
                    context_policy_version=POLICY, graph_schema=SCHEMA,
                    target_masking_version=MASKING, budget_policy=BUDGET_POLICY,
                    contract_version=CONTRACT_VERSION, source_commit=self.source_commit,
                    source_hash=self.source_hash, dependency_hash=self.dependency_hash,
                    tokenizer_fingerprint=fingerprint, input_length=input_length, label_length=label_length)
        if target.file in self.resolver.parse_failures:
            return dict(base, outcome='parse_error', input=None, gaps=[dict(reason='source_parse_error')])
        definition = self.resolver.target(target)
        if definition is None:
            return dict(base, outcome='target_not_found', input=None, gaps=[dict(reason='exact_target_identity_missing')])
        # Mask matching definition copies across all source files before reading
        # annotations or rendering any source support, including reexports.
        overlays = MaskedSources(self.sources, target.function, target.name, target.scope)
        overlay_trees = {}  # populated only for source files actually rendered

        def view(definition):
            if definition.file not in overlay_trees:
                overlay_trees[definition.file] = ast.parse(overlays[definition.file])
            if definition.qualified=='<module>':
                return self.resolver.module_function(overlay_trees[definition.file])
            matches = [n for q, n in functions(overlay_trees[definition.file]) if q == definition.qualified]
            return matches[definition.occurrence]

        builder = self._builder(definition)
        graph = builder.graph
        if target.scope == 'arg':
            if target.name not in builder.parameters:
                return dict(base, outcome='target_not_found', input=None, gaps=[dict(reason='parameter_missing')])
            graph.seeds.add(builder.parameters[target.name])
            graph.seeds.update(n.id for n in graph.nodes.values() if n.symbol == target.name and n.scope==definition.qualified)
        else:
            graph.seeds.update(builder.returns or builder.terminal_exits or {builder.node(definition.node,'no_return')})
        builders = [(definition, builder, 0, ())]
        attached_calls=set()
        caller_expansions=0
        for caller,call,rule in self.resolver.incoming_calls(definition.key):
            if caller.key==definition.key:
                continue  # recursive effects are handled by SCC summaries
            if caller_expansions>=self.max_expansions:
                graph.gap(next(iter(sorted(graph.seeds))),'caller_expansion_limit',[str(caller.key)])
                break
            if definition.node.decorator_list:
                graph.gap(next(iter(sorted(graph.seeds))),'decorated_target_caller_not_closed',[str(caller.key)])
                continue
            bindings=bind_arguments(call,definition.node,self.resolver.bound_receiver(caller,call,definition))
            if bindings is None:
                graph.gap(next(iter(sorted(graph.seeds))),'caller_argument_binding_unresolved',[str(caller.key)])
                continue
            selected_bindings=[(actual,formal) for actual,formal in bindings if target.scope=='return' or formal==target.name]
            if not selected_bindings:
                continue
            caller_builder=self._builder(caller,digest((target.identity,caller.key,call.lineno,call.col_offset)))
            caller_calls=[identifier for identifier,node in caller_builder.calls.items() if node is call]
            if len(caller_calls)!=1:
                continue
            caller_call=caller_calls[0]
            graph.nodes.update(caller_builder.graph.nodes)
            graph.edges.update(caller_builder.graph.edges)
            for actual,formal in selected_bindings:
                actual_nodes=[n.id for n in caller_builder.graph.nodes.values() if n.span.start==actual.lineno
                              and n.span.column==actual.col_offset and n.text==ast.unparse(actual)]
                if not actual_nodes:
                    # Default values are defined in the target's source.
                    actual_nodes=list(builder.expr(actual,{}))
                for actual_id in actual_nodes:
                    graph.link(actual_id,builder.parameters[formal],'argument',rule+':verified_caller_binding','verified')
            for returned in builder.returns:
                graph.link(returned,caller_call,'call_result',rule+':verified_caller_return','verified')
            attached_calls.add(caller_call)
            builders.append((caller,caller_builder,1,(definition.key,)))
            caller_expansions+=1
        groups = []
        seen_groups = set()
        expanded = caller_expansions
        while builders:
            current, current_builder, distance, ancestry = builders.pop(0)
            node = view(current)
            group_id = digest(current.key)
            if group_id not in seen_groups:
                seen_groups.add(group_id)
                # Retaining complete function scopes is the conservative initial
                # policy. It avoids rendering sliced control structures as source.
                groups.append(EvidenceGroup(group_id, current.file, node.lineno, node.end_lineno,
                    '\n'.join(ast.unparse(stmt) for stmt in node.body) if current.qualified=='<module>' else ast.unparse(node), tuple(sorted(current_builder.graph.nodes)),
                    mandatory=distance == 0, priority=2 if any(k in attached_calls for k in current_builder.calls) else 0, distance=distance, owner=current.qualified))
            else:
                groups = [replace(g, node_ids=tuple(sorted(set(g.node_ids) | set(current_builder.graph.nodes))))
                          if g.id == group_id else g for g in groups]
            current_graph = current_builder.graph
            if current_builder is not builder:
                graph.nodes.update(current_graph.nodes)
                graph.edges.update(current_graph.edges)
                for gap in current_graph.gaps:
                    graph.gap(gap['node'], gap['reason'], gap['possible_bindings'])
            local_names = set(current_builder.parameters)
            local_names.update(n.symbol for n in current_graph.nodes.values() if n.kind == 'binding')
            def local_nodes(node):
                yield node
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                        continue
                    yield from local_nodes(child)
            body_nodes = [n for stmt in current.node.body for n in local_nodes(stmt)]
            local_names.update(n.id for n in body_nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store))
            local_names.update(a.asname or a.name.split('.')[0] for n in body_nodes
                               if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names)
            for call_id, call in current_builder.calls.items():
                if call_id in attached_calls:
                    continue
                if call_id in current_builder.builtin_calls:
                    for edge in list(graph.edges):
                        if edge.source==call_id and edge.kind=='field_write':
                            graph.link(edge.source,edge.target,'element','literal_'+current_builder.builtin_calls[call_id],'verified')
                    continue
                matches, rule = self.resolver.resolve(current, call, local_names)
                if rule.startswith('builtin_known:'):
                    continue
                if rule.startswith('builtin:'):
                    if any(isinstance(a,ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords):
                        graph.gap(call_id,'builtin_argument_expansion_unresolved')
                        continue
                    from typepro.analysis.graph_contracts import apply_builtin_contract
                    apply_builtin_contract(graph,call_id,call,rule.split(':',1)[1])
                    if rule=='builtin:map':
                        if len(call.args)<2:
                            graph.gap(call_id,'map_callback_arity_unresolved')
                            continue
                        callback=call.args[0]
                        probe=ast.copy_location(ast.Call(func=callback,args=[],keywords=[]),call)
                        callbacks,callback_rule=self.resolver.resolve(current,probe,local_names)
                        if callback_rule.startswith(('builtin:','builtin_known:')):
                            continue
                        if len(callbacks)!=1 or callbacks[0].node.decorator_list:
                            graph.gap(call_id,'callback_summary_not_closed',[str(d.key) for d in callbacks])
                            continue
                        callback_definition=callbacks[0]
                        positional=callback_definition.node.args.posonlyargs+callback_definition.node.args.args
                        required=len(positional)-len(callback_definition.node.args.defaults)
                        count=len(call.args)-1
                        if not required<=count<=len(positional) or any(d is None for d in callback_definition.node.args.kw_defaults):
                            graph.gap(call_id,'map_callback_arity_unresolved',[str(callback_definition.key)])
                            continue
                        if callback_definition.key in ancestry or callback_definition.key==current.key or expanded>=self.max_expansions:
                            graph.gap(call_id,'callback_expansion_limit',[str(callback_definition.key)])
                            continue
                        expanded+=1
                        callback_builder=self._builder(callback_definition,'map:'+call_id)
                        graph.nodes.update(callback_builder.graph.nodes)
                        graph.edges.update(callback_builder.graph.edges)
                        for index,(iterable,formal) in enumerate(zip(call.args[1:],positional)):
                            element_id=digest((call_id,'callback_element',index))
                            graph.nodes[element_id]=Node(element_id,'element',current_builder.scope,
                                Span(current.file,iterable.lineno,iterable.end_lineno,iterable.col_offset),
                                self.file_hashes[current.file],ast.unparse(iterable),'map_element')
                            for operand in list(current_graph.nodes.values()):
                                if operand.text==ast.unparse(iterable) and operand.span.start==iterable.lineno and operand.span.column==iterable.col_offset and operand.id!=element_id:
                                    graph.link(operand.id,element_id,'element','builtin_map_iterable_element','verified')
                            graph.link(element_id,callback_builder.parameters[formal.arg],'argument','builtin_map_callback_formal','verified')
                        for returned in callback_builder.returns:
                            graph.link(returned,call_id,'element','builtin_map_result_element','verified')
                        builders.append((callback_definition,callback_builder,distance+1,(*ancestry,current.key)))
                    continue
                if not matches:
                    graph.gap(call_id, rule)
                    continue
                if len(matches) != 1:
                    graph.gap(call_id, 'multiple_lexical_definitions', [str(m.key) for m in matches])
                    for possible in matches:
                        candidate_id=digest(('ambiguous-definition',possible.key,call_id))
                        node=view(possible)
                        graph.nodes[candidate_id]=Node(candidate_id,'symbol',current_builder.scope,
                            Span(possible.file,node.lineno,node.end_lineno,node.col_offset),self.file_hashes[possible.file],
                            ast.unparse(possible.node),possible.qualified)
                        graph.link(candidate_id,call_id,'call_result','ambiguous_source_candidate')
                        groups.append(EvidenceGroup(candidate_id,possible.file,node.lineno,node.end_lineno,
                            ast.unparse(node),(candidate_id,),priority=4,owner=possible.qualified))
                    continue
                callee = matches[0]
                if any(ast.unparse(d) not in {'staticmethod','classmethod'} or not self.resolver.symbols.is_builtin(callee,ast.unparse(d)) for d in callee.node.decorator_list):
                    graph.gap(call_id, 'decorator_changes_callable', [str(callee.key)])
                    continue
                receiver=self.resolver.bound_receiver(current,call,callee)
                bindings = bind_arguments(call, callee.node,receiver)
                if rule=='receiver_member':
                    graph.gap(call_id,'receiver_dispatch_not_closed',[str(callee.key)])
                if bindings is None:
                    graph.gap(call_id, 'argument_binding_unresolved', [str(callee.key)])
                    continue
                if callee.key in ancestry or callee.key == current.key:
                    if self._recursive_summaries is None:
                        from typepro.analysis.graph_summaries import summarize
                        self._recursive_summaries=summarize(self.resolver)
                    summary=self._recursive_summaries[callee.key]
                    graph.gap(call_id, 'recursive_summary_not_closed', [str(callee.key)])
                    if summary['truncated']:
                        graph.gap(call_id,'recursive_summary_limit')
                    for returned in current_builder.returns:
                        graph.link(returned,call_id,'call_result','scc_fixed_point_return_sites')
                    continue
                if expanded >= self.max_expansions:
                    graph.gap(call_id, 'expansion_limit', [str(callee.key)])
                    continue
                expanded += 1
                # Callsite-specific scope IDs prevent unrelated actuals/formals
                # from joining across different callers.
                callee_builder = self._builder(callee, call_id)
                callee_graph = callee_builder.graph
                graph.nodes.update(callee_graph.nodes)
                graph.edges.update(callee_graph.edges)
                for actual, formal in bindings:
                    from_callsite = actual is receiver or any(actual is arg for arg in call.args) or any(actual is keyword.value for keyword in call.keywords)
                    actual_nodes = [n.id for n in current_graph.nodes.values()
                                    if from_callsite
                                    and n.span.start == getattr(actual, 'lineno', -1)
                                    and n.span.column == getattr(actual, 'col_offset', -1)
                                    and n.text==ast.unparse(actual) and n.kind!='unresolved']
                    if not actual_nodes:
                        # Defaults originate in the callee's source, not caller.
                        actual_nodes = list(callee_builder.expr(actual, {}))
                        graph.nodes.update(callee_graph.nodes)
                        graph.edges.update(callee_graph.edges)
                    for actual_id in actual_nodes:
                        graph.link(actual_id, callee_builder.parameters[formal], 'argument', rule + ':formal_binding', 'verified')
                for returned in callee_builder.returns:
                    graph.link(returned, call_id, 'call_result', rule + ':return_summary', 'verified')
                builders.append((callee, callee_builder, distance + 1, (*ancestry, current.key)))
        # Unbound uses require source identity. Never report a dynamic/global
        # name as closed merely because it occurs in the target's source text.
        incoming={e.target for e in graph.edges if e.kind in {'def_use','argument','assign'}}
        for use in list(graph.nodes.values()):
            if use.kind!='use' or use.id in incoming:
                continue
            lexical=use.scope.split('@',1)[0]
            candidates=self.resolver.by_scope.get((use.span.file,lexical),[])
            owner=candidates[0] if len(candidates)==1 else self.resolver.module_definitions.get(use.span.file,definition)
            binding=self.resolver.module_binding(owner,use.symbol)
            if binding is None:
                # Builtins still require absence of a lexical assignment. The
                # resolver separately guards contracts against monkey-patching.
                local_names={n.symbol for n in graph.nodes.values() if n.kind in {'binding','parameter'} and n.scope==use.scope}
                if self.resolver.symbols.is_builtin(owner,use.symbol,local_names):
                    continue
                else:
                    graph.gap(use.id,'nonlocal_binding_not_closed',[use.symbol])
                continue
            symbol_id=digest(('module-binding',use.span.file,binding.lineno,use.symbol))
            graph.nodes[symbol_id]=Node(symbol_id,'symbol',owner.qualified,
                Span(use.span.file,binding.lineno,binding.end_lineno,binding.col_offset),
                self.file_hashes[use.span.file],ast.unparse(binding),use.symbol)
            graph.link(symbol_id,use.id,'def_use','exact_module_binding')
            if isinstance(binding,(ast.Assign,ast.AnnAssign)) and isinstance(binding.value,(ast.Call,ast.Attribute,ast.Subscript)):
                graph.gap(symbol_id,'module_initialization_effect_not_closed',[use.symbol])
        covered_spans={(g.file,g.start,g.end) for g in groups}
        for symbol in list(graph.nodes.values()):
            span=symbol.span
            if symbol.kind!='symbol' or (span.file,span.start,span.end) in covered_spans:
                continue
            raw_tree=ast.parse(overlays[span.file])
            matches=[n for n in raw_tree.body if n.lineno==span.start and n.end_lineno==span.end]
            if len(matches)==1:
                groups.append(EvidenceGroup(digest(('module_source',symbol.id)),span.file,span.start,span.end,
                                           ast.unparse(matches[0]),(symbol.id,),priority=1))
                covered_spans.add((span.file,span.start,span.end))
        from typepro.analysis.graph_support import support_groups, dependency_groups
        relevant=dependency_closure(graph,target.scope)
        for key in sorted(seen_groups):
            group=next(g for g in groups if g.id==key)
            if group.mandatory or set(group.node_ids)&relevant:
                for supported in self.resolver.definitions.values():
                    if digest(supported.key)==key:
                        groups.extend(support_groups(target,supported,overlays,graph,self.resolver))
        groups.extend(dependency_groups(target, overlays, graph, self.dependency_kb))
        from typepro.analysis.graph_hypotheses import source_hypotheses
        groups.extend(source_hypotheses(target,definition,overlays,graph))
        selected_nodes = dependency_closure(graph, target.scope)
        excerpts = {}
        for definition_key in seen_groups:
            # Group IDs are canonical source definitions, independent of callsite.
            group = next(g for g in groups if g.id == definition_key)
            definitions = [d for d in self.resolver.definitions.values() if digest(d.key) == definition_key]
            if definitions:
                d = definitions[0]
                scopes = {graph.nodes[k].scope for k in group.node_ids if k in graph.nodes}
                # Union the relevant nodes across all instantiated callsites.
                if any(graph.nodes[gap['node']].scope in scopes for gap in graph.gaps):
                    continue
                combined = deepcopy(graph)
                canonical = d.qualified
                combined.nodes = {k: replace(n, scope=canonical) if n.scope in scopes else n for k,n in graph.nodes.items()}
                excerpts[group.id] = render_function_excerpt(view(d), combined, canonical, selected_nodes)
        groups = [replace(g, text=excerpts[g.id]) if g.id in excerpts else g for g in groups]
        # A selected evidence path must retain the source groups containing its
        # support. Lexical/module hypotheses remain optional.
        groups = [replace(g,node_ids=tuple(sorted(set(g.node_ids)|{n.id for n in graph.nodes.values()
                    if n.kind=='symbol' and n.span.file==g.file and n.span.start==g.start and n.span.end==g.end}))) for g in groups]
        unrelated_groups={g.id:'no_target_dependency_path' for g in groups
                          if not g.mandatory and g.priority!=4 and g.node_ids and not set(g.node_ids)&selected_nodes}
        prerequisite_ids={p for g in groups for p in g.prerequisites}
        unrelated_groups={k:v for k,v in unrelated_groups.items() if k not in prerequisite_ids}
        unrelated_evidence=[g for g in groups if g.id in unrelated_groups]
        groups=[g for g in groups if g.id not in unrelated_groups]
        groups = [replace(g,mandatory=True) if set(g.node_ids)&selected_nodes else g for g in groups]
        groups = canonicalize_groups(groups)
        from typepro.analysis.graph_conflicts import annotation_conflicts
        conflicts=annotation_conflicts(groups)
        packed = pack_groups(tokenizer, groups, lambda gs: render_groups(target, gs), input_length, label_length)
        outcome = packed.outcome
        if outcome == 'ready' and graph.gaps:
            outcome = 'unresolved'
        base.update(outcome=outcome, input=packed.instruction if outcome != 'budget_exceeded' else None,
                    full_evidence=[asdict(g) for g in [*groups,*unrelated_evidence]],
                    audit=dict(graph=graph.serialize(), selected_node_ids=sorted(selected_nodes),
                               retained_groups=packed.retained, omitted_groups={**unrelated_groups,**packed.omitted},
                               conflicts=conflicts, prompt_tokens=len(packed.prompt_ids),
                               mandatory_tokens=packed.required_tokens,
                               resolved_edges=sum(e.certainty == 'verified' for e in graph.edges),
                               unresolved_count=len(graph.gaps),
                               query_seconds=time.monotonic() - started, project_build_seconds=self.build_seconds,
                               structural_cache_hits=self.cache_hits, structural_cache_misses=self.cache_misses,
                               cached_structural_nodes=self._summary_nodes, accounted_structural_cache_bytes=self._summary_bytes),
                    gaps=graph.gaps, recursive_summaries=[] if self._recursive_summaries is None else
                    [dict(function=list(k),**v) for k,v in self._recursive_summaries.items() if v['recursive']])
        base['cache_key'] = digest(dict(target=asdict(target), structural_hash=self.structural_hash,
            dependency=self.dependency_hash, source_commit=self.source_commit, schema=SCHEMA, masking=MASKING,
            module_aliases=self.resolver.symbols.aliases,
            policy=POLICY, contracts=CONTRACT_VERSION, budget=BUDGET_POLICY,
            allowed_source_hashes={f:digest(ast.dump(ast.parse(s),include_attributes=False)) for f,s in overlays.cache.items()},
            tokenizer=fingerprint, input_length=input_length, label_length=label_length,
            max_expansions=self.max_expansions))
        return base
