"""Low-priority declaration hypotheses from masked source, never resolved edges.

Name overlap and visible unpack shape nominate declarations. They cannot remove
or replace any mandatory dependency or resolve an unknown fixture/receiver.
"""
from __future__ import annotations
import ast
import re
from typepro.analysis.evidence_graph import Node, Span, digest
from typepro.analysis.graph_builder import functions
from typepro.analysis.graph_selection import EvidenceGroup


def name_tokens(name):
    split=re.sub(r'([a-z0-9])([A-Z])',r'\1_\2',name)
    return set(re.findall(r'[a-z]+',split.lower()))-{'and','or','the','get','set','is'}


def source_hypotheses(target,definition,overlays,graph):
    if target.scope!='arg' or definition.file!=target.file or definition.qualified!=target.function:
        return []
    tree=ast.parse(overlays[target.file])
    targets=[n for qualified,n in functions(tree) if qualified==definition.qualified]
    function=targets[definition.occurrence]
    arities=set()
    for node in ast.walk(function):
        if isinstance(node,ast.Assign) and isinstance(node.value,ast.Name) and node.value.id==target.name:
            arities.update(len(t.elts) for t in node.targets if isinstance(t,(ast.Tuple,ast.List)))
    imports={}
    for stmt in tree.body:
        if isinstance(stmt,(ast.Import,ast.ImportFrom)):
            for alias in stmt.names:
                imports[alias.asname or alias.name.split('.')[0]]=stmt
    groups=[]
    retained_imports=set()
    target_tokens=name_tokens(target.name)
    for statement in tree.body:
        if isinstance(statement,ast.Assign) and len(statement.targets)==1 and isinstance(statement.targets[0],ast.Name):
            name=statement.targets[0].id
            value=statement.value
        elif isinstance(statement,ast.AnnAssign) and isinstance(statement.target,ast.Name):
            name,value=statement.target.id,statement.value
        else:
            continue
        if value is None or not name.lstrip('_')[:1].isupper():
            continue
        # Restrict candidates to source-declared type forms, not arbitrary
        # uppercase runtime expressions. Import identity verifies typing.Tuple.
        type_form=False; shape=None
        if isinstance(value,ast.Subscript):
            base=value.value
            if isinstance(base,ast.Name) and base.id in {'tuple','list','dict','set'} and base.id not in imports:
                type_form=True
                if base.id=='tuple' and isinstance(value.slice,ast.Tuple):
                    shape=len(value.slice.elts)
            elif isinstance(base,ast.Name) and base.id in imports:
                stmt=imports[base.id]
                aliases=[a for a in stmt.names if (a.asname or a.name)==base.id]
                type_form=isinstance(stmt,ast.ImportFrom) and stmt.module in {'typing','typing_extensions'}
                if type_form and aliases and aliases[0].name=='Tuple' and isinstance(value.slice,ast.Tuple):
                    shape=len(value.slice.elts)
            elif isinstance(base,ast.Attribute) and isinstance(base.value,ast.Name) and base.value.id in imports:
                stmt=imports[base.value.id]
                type_form=isinstance(stmt,ast.Import) and any(a.name in {'typing','typing_extensions'} for a in stmt.names)
                if type_form and base.attr=='Tuple' and isinstance(value.slice,ast.Tuple):
                    shape=len(value.slice.elts)
        elif isinstance(statement,ast.AnnAssign):
            type_form=ast.unparse(statement.annotation).endswith('TypeAlias')
        if not type_form or not (target_tokens & name_tokens(name) or shape in arities):
            continue
        prerequisites=[]
        for use in ast.walk(value):
            if not isinstance(use,ast.Name) or use.id not in imports:
                continue
            imported=imports[use.id]
            identifier=digest((target.file,imported.lineno,'hypothesis_import'))
            prerequisites.append(identifier)
            if identifier not in retained_imports:
                retained_imports.add(identifier)
                groups.append(EvidenceGroup(identifier,target.file,imported.lineno,imported.end_lineno,
                                            ast.unparse(imported),priority=4))
        identifier=digest((target.file,statement.lineno,'declaration_hypothesis',name))
        graph.nodes[identifier]=Node(identifier,'hypothesis','hypothesis:'+target.file,
            Span(target.file,statement.lineno,statement.end_lineno,statement.col_offset),digest(overlays[target.file]),
            ast.unparse(statement),name)
        for seed in graph.seeds:
            graph.link(seed,identifier,'hypothesis','masked_name_or_unpack_shape_candidate')
        groups.append(EvidenceGroup(identifier,target.file,statement.lineno,statement.end_lineno,ast.unparse(statement),
                                    (identifier,),tuple(sorted(set(prerequisites))),priority=4))
    return groups
