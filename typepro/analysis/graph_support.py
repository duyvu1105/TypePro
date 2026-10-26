"""Scoped source support for fields, aliases and pytest fixtures.

These are source evidence with provenance. May edges retain uncertainty about
runtime mutation, inheritance and plugins rather than asserting runtime identity.
"""
from __future__ import annotations
import ast
from copy import deepcopy
from pathlib import PurePosixPath
from typepro.analysis.evidence_graph import Node, Span, digest
from typepro.analysis.graph_selection import EvidenceGroup
from typepro.analysis.graph_builder import functions, FUNCTIONS
from typepro.analysis.target_context import MASK


def support_groups(target, definition, overlays, graph, resolver=None):
    tree = ast.parse(overlays[definition.file])
    matches = [n for q,n in functions(tree) if q == definition.qualified]
    function = matches[definition.occurrence]
    groups = []
    seed = next(iter(sorted(graph.seeds)), None)
    if seed is None:
        return groups

    def add(node, kind, file, rule, prerequisite=(), text=None, certainty='may',owner='',priority=1):
        identifier = digest((file, getattr(node,'lineno',0), getattr(node,'col_offset',0), kind, rule))
        graph.nodes[identifier] = Node(identifier, kind, definition.qualified,
            Span(file, node.lineno, node.end_lineno, node.col_offset), digest(overlays[file]),
            ast.unparse(node), rule)
        graph.link(identifier, seed, kind, rule, certainty)
        group_id = digest(('source_support',identifier))
        groups.append(EvidenceGroup(group_id,file,node.lineno,node.end_lineno,
            text if text is not None else ast.unparse(node),(identifier,), prerequisite, priority=priority,
            owner=owner))
        return group_id

    # Follow module declarations using exact Name dependencies. Cycles are gaps,
    # never unbounded recursive alias expansion. No guessed short-name matching.
    declarations = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for lhs in stmt.targets:
                if isinstance(lhs,ast.Name):
                    declarations.setdefault(lhs.id, []).append(stmt)
        elif isinstance(stmt,ast.AnnAssign) and isinstance(stmt.target,ast.Name):
            declarations.setdefault(stmt.target.id, []).append(stmt)
    from typepro.analysis.graph_selection import dependency_closure
    selected=dependency_closure(graph,target.scope)
    pending={n.symbol for key,n in graph.nodes.items() if key in selected and n.kind=='use'
             and n.scope.split('@',1)[0]==definition.qualified and n.span.file==definition.file}
    annotations=[a.annotation for a in function.args.posonlyargs+function.args.args+function.args.kwonlyargs if a.annotation]
    if function.returns:
        annotations.append(function.returns)
    pending.update(n.id for annotation in annotations for n in ast.walk(annotation) if isinstance(n,ast.Name) and n.id!=MASK)
    pending=sorted(pending)
    visited = set()
    def visit(name, path=()):
        if name in path:
            graph.gap(seed,'alias_cycle', (*path,name))
            return
        if name in visited or name not in declarations:
            return
        visited.add(name)
        if len(declarations[name]) != 1:
            graph.gap(seed,'ambiguous_module_declaration',[name])
            return
        stmt = declarations[name][0]
        add(stmt,'alias',definition.file,'exact_module_declaration:'+name)
        value = stmt.value
        if value is not None:
            for child in ast.walk(value):
                if isinstance(child,ast.Name) and isinstance(child.ctx,ast.Load):
                    visit(child.id,(*path,name))
    for name in pending:
        visit(name)

    # Follow source-owned receiver fields, constructors and properties through
    # exact base declarations. A source declaration is evidence, not a claim
    # that Python runtime dispatch cannot override it.
    owner_path = definition.qualified.rsplit('.',1)[0] if '.' in definition.qualified else ''
    def classes(node,prefix=''):
        for item in node.body:
            if isinstance(item,ast.ClassDef):
                q=(prefix+'.' if prefix else '')+item.name
                yield q,item
                yield from classes(item,q)
    class_views={}
    def class_view(file,qualified):
        if file not in class_views:
            class_views[file]=dict(classes(ast.parse(overlays[file])))
        return class_views[file].get(qualified)
    requested={}
    for expression in ast.walk(function):
        if not isinstance(expression,ast.Attribute):
            continue
        if resolver is not None:
            receivers=resolver.symbols.receiver_classes(definition,expression.value,expression)
        elif isinstance(expression.value,ast.Name) and expression.value.id in {'self','cls'}:
            owner=class_view(definition.file,owner_path)
            receivers=[(definition.file,owner_path,owner)] if owner is not None else []
        else:
            receivers=[]
        for file,qualified,_ in receivers:
            requested.setdefault((file,qualified),set()).add(expression.attr)
    owners_added={}
    members_added=set()
    processed_fields={}
    def retain_owner(file,qualified):
        key=(file,qualified)
        if key not in owners_added:
            owner=class_view(file,qualified)
            header=deepcopy(owner)
            header.body=([deepcopy(owner.body[0])] if ast.get_docstring(owner) else [])+[ast.Pass()]
            owners_added[key]=add(owner,'annotation',file,'lexical_class_owner',text=ast.unparse(header),owner=qualified)
        return owners_added[key]
    def retain_member(file,qualified,member):
        key=(file,qualified,member.lineno)
        if key in members_added:
            return
        members_added.add(key)
        add(member,'field_read',file,'lexical_owner_member',(retain_owner(file,qualified),),owner=qualified)
    def search(file,qualified,fields,ancestry=()):
        key=(file,qualified)
        if key in ancestry:
            graph.gap(seed,'class_alias_or_inheritance_cycle',[str(key)])
            return
        new_fields=set(fields)-processed_fields.get(key,set())
        if not new_fields:
            return
        processed_fields.setdefault(key,set()).update(new_fields)
        fields=new_fields
        owner=class_view(file,qualified)
        if owner is None:
            return
        retain_owner(file,qualified)
        remaining=set(fields)
        follow=set()
        for member in owner.body:
            names=set()
            if isinstance(member,ast.AnnAssign) and isinstance(member.target,ast.Name):
                names.add(member.target.id)
            elif isinstance(member,ast.Assign):
                names.update(t.id for t in member.targets if isinstance(t,ast.Name))
            elif isinstance(member,FUNCTIONS):
                names.add(member.name)
            if names & fields:
                retain_member(file,qualified,member)
                remaining-=names
                if isinstance(member,FUNCTIONS):
                    follow.update(n.attr for n in ast.walk(member) if isinstance(n,ast.Attribute)
                                  and isinstance(n.value,ast.Name) and n.value.id in {'self','cls'})
            if isinstance(member,FUNCTIONS) and member.name=='__init__':
                writes={n.attr for n in ast.walk(member) if isinstance(n,ast.Attribute) and isinstance(n.ctx,ast.Store)
                        and isinstance(n.value,ast.Name) and n.value.id=='self'}
                if writes & fields:
                    retain_member(file,qualified,member)
                    remaining-=writes
        follow-=fields
        if follow:
            search(file,qualified,follow,ancestry)
        if remaining and resolver is not None:
            for base in owner.bases:
                references,_=resolver.symbols.file_references(file,ast.unparse(base))
                for base_file,base_name,node in references:
                    if isinstance(node,ast.ClassDef):
                        search(base_file,base_name,remaining,(*ancestry,key))
        if owner.decorator_list:
            graph.gap(seed,'class_decorator_dispatch_not_closed',[ast.unparse(d) for d in owner.decorator_list])
        if owner.bases:
            graph.gap(seed,'inheritance_dispatch_not_closed',[ast.unparse(b) for b in owner.bases])
    for (file,qualified),fields in sorted(requested.items()):
        search(file,qualified,fields)

    # Pytest injection is scoped to the module and its ancestor conftest files.
    # Explicit parametrize has precedence; plugin fixtures are left unresolved.
    if target.scope=='arg' and definition.file==target.file and definition.qualified==target.function and function.name.startswith('test_'):
        parametrized=False
        for decorator in function.decorator_list:
            if isinstance(decorator,ast.Call) and ast.unparse(decorator.func).endswith('.parametrize') and decorator.args:
                names=decorator.args[0]
                if isinstance(names,ast.Constant) and isinstance(names.value,str):
                    parametrized |= target.name in {v.strip() for v in names.value.split(',')}
        if parametrized:
            graph.gap(seed,'pytest_parametrize_requires_runtime_binding',[target.name])
        else:
            from typepro.analysis.graph_fixtures import fixture_evidence
            fixtures,gaps=fixture_evidence(target,definition,overlays,resolver)
            for file,node,rule in fixtures:
                add(node,'annotation',file,rule,priority=2)
            for reason,bindings in gaps:
                graph.gap(seed,reason,bindings)
    return groups


def dependency_groups(target, overlays, graph, dependency_kb):
    """Exact imported symbols from a frozen project KB, masked before selection.

    This supplies declaration evidence, not a proof of runtime library dispatch.
    KB metadata other than identity/source is never an annotation-derived score.
    """
    from typepro.analysis.target_context import mask_definition
    tree=ast.parse(overlays[target.file])
    imported={}
    for stmt in tree.body:
        if isinstance(stmt,ast.Import):
            for alias in stmt.names:
                imported[alias.asname or alias.name.split('.')[0]]=alias.name if alias.asname else alias.name.split('.')[0]
        elif isinstance(stmt,ast.ImportFrom) and not stmt.level:
            for alias in stmt.names:
                imported[alias.asname or alias.name]=(stmt.module+'.'+alias.name) if stmt.module else alias.name
    needed=set()
    for _,node in functions(tree):
        if node.name!=target.function.rsplit('.',1)[-1]:
            continue
        for expr in ast.walk(node):
            if isinstance(expr,(ast.Name,ast.Attribute)):
                name=ast.unparse(expr)
                root,_,suffix=name.partition('.')
                if root in imported:
                    needed.add(imported[root]+('.'+suffix if suffix else ''))
    groups=[]
    seed=next(iter(sorted(graph.seeds)),None)
    if seed is None:
        return groups
    for record in dependency_kb.get('records',[]):
        qualified=record.get('qualified_name')
        if qualified not in needed:
            continue
        text=mask_definition(str(record.get('definition') or ''),target.function,target.name,target.scope)
        try:
            parsed=ast.parse(text)
        except (SyntaxError,ValueError):
            graph.gap(seed,'dependency_definition_not_parseable',[qualified])
            continue
        if not parsed.body:
            continue
        identifier=digest(('dependency',qualified,text))
        file='dependency:'+str(record.get('source_file') or record.get('module') or qualified)
        graph.nodes[identifier]=Node(identifier,'annotation',qualified,Span(file,1,len(text.splitlines())),
                                    digest(text),text,qualified)
        graph.link(identifier,seed,'annotation','frozen_kb_exact_import','may')
        groups.append(EvidenceGroup(identifier,file,1,len(text.splitlines()),text,(identifier,),priority=0,owner=qualified))
    return groups
