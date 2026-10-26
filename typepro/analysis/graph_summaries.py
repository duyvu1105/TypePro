"""Annotation-free call SCCs and bounded monotone source-return summaries."""
from __future__ import annotations
import ast
from typepro.analysis.graph_builder import FUNCTIONS

VERSION='graph-structural-summaries-v1'


def scope_nodes(function):
    stack=list(reversed(function.body))
    while stack:
        node=stack.pop()
        yield node
        if isinstance(node,(*FUNCTIONS,ast.ClassDef,ast.Lambda)):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def summarize(resolver, limit=128):
    adjacency={key:set() for key in resolver.definitions}
    own={}
    for key,definition in resolver.definitions.items():
        nodes=list(scope_nodes(definition.node))
        args=definition.node.args
        bound={a.arg for a in args.posonlyargs+args.args+args.kwonlyargs}
        bound.update(a.arg for a in (args.vararg,args.kwarg) if a)
        bound.update(n.id for n in nodes if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store))
        own[key]={(definition.file,definition.qualified,n.lineno) for n in nodes
                  if isinstance(n,(ast.Return,ast.Yield,ast.YieldFrom))}
        for node in nodes:
            if isinstance(node,ast.Call):
                matches,_=resolver.resolve(definition,node,bound)
                adjacency[key].update(m.key for m in matches)
    # Iterative Kosaraju avoids depending on Python recursion depth for projects
    # with many functions. All identities include canonical file and occurrence.
    visited=set(); order=[]
    for root in sorted(adjacency):
        if root in visited:
            continue
        stack=[(root,False)]
        while stack:
            node,done=stack.pop()
            if done:
                order.append(node)
                continue
            if node in visited:
                continue
            visited.add(node)
            stack.append((node,True))
            stack.extend((child,False) for child in sorted(adjacency[node],reverse=True) if child not in visited)
    reverse={key:set() for key in adjacency}
    for key,children in adjacency.items():
        for child in children:
            reverse[child].add(key)
    components=[]; component_of={}
    for root in reversed(order):
        if root in component_of:
            continue
        index=len(components); members=set(); pending=[root]
        while pending:
            node=pending.pop()
            if node in component_of:
                continue
            component_of[node]=index; members.add(node)
            pending.extend(reverse[node]-component_of.keys())
        components.append(members)
    returns={i:set().union(*(own[k] for k in members)) for i,members in enumerate(components)}
    truncated={i:len(v)>limit for i,v in returns.items()}
    returns={i:set(sorted(v)[:limit]) for i,v in returns.items()}
    dependencies={i:{component_of[c] for k in members for c in adjacency[k] if component_of[c]!=i}
                  for i,members in enumerate(components)}
    # Component DAG reaches a finite fixed point; the cap is explicit metadata.
    changed=True
    while changed:
        changed=False
        for i in range(len(components)):
            combined=returns[i]|set().union(*(returns[c] for c in dependencies[i]))
            capped=set(sorted(combined)[:limit])
            overflow=truncated[i] or len(combined)>limit or any(truncated[c] for c in dependencies[i])
            if capped!=returns[i] or overflow!=truncated[i]:
                returns[i]=capped; truncated[i]=overflow; changed=True
    return {key:dict(component=sorted(components[component_of[key]]),
                     return_sites=sorted(returns[component_of[key]]),
                     truncated=truncated[component_of[key]],
                     recursive=len(components[component_of[key]])>1 or key in adjacency[key],version=VERSION)
            for key in adjacency}
