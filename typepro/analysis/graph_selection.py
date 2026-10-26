"""Evidence groups keep source ownership and dependency paths intact."""
from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceGroup:
    id: str
    file: str
    start: int
    end: int
    text: str
    node_ids: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()
    mandatory: bool = False
    priority: int = 0
    distance: int = 0
    owner: str = ''


def dependency_closure(graph, target_scope='return'):
    selected = set(graph.seeds)
    # An unresolved effect can influence its entire lexical scope. Retaining
    # the scope also requires the source definitions referenced inside it.
    gap_scopes={graph.nodes[g['node']].scope for g in graph.gaps}
    selected.update(n.id for n in graph.nodes.values() if n.scope in gap_scopes)
    if target_scope == 'arg':
        while True:
            expanded = selected | {e.target for e in graph.edges if e.source in selected
                                   and e.kind in {'def_use', 'assign', 'argument', 'return', 'yield', 'call_result', 'field_read', 'field_write', 'element','merge','unpack'}}
            if expanded == selected:
                break
            selected = expanded
    while True:
        expanded = selected | {e.source for e in graph.edges if e.target in selected}
        if expanded == selected:
            return selected
        selected = expanded


def ordered_groups(groups):
    return sorted(groups, key=lambda g: (not g.mandatory, g.priority, g.distance, len(g.text), g.id))


def canonicalize_groups(groups):
    """Deduplicate exact canonical excerpts, retaining prerequisites and conflicts."""
    from dataclasses import replace
    buckets={}
    for group in groups:
        buckets.setdefault((group.file,group.start,group.end,group.owner,group.text),[]).append(group)
    remap={}
    for members in buckets.values():
        canonical=min(g.id for g in members)
        remap.update({g.id:canonical for g in members})
    result=[]
    for members in buckets.values():
        first=min(members,key=lambda g:g.id)
        prerequisites={remap[p] for g in members for p in g.prerequisites}
        prerequisites.discard(first.id)
        result.append(replace(first,node_ids=tuple(sorted({n for g in members for n in g.node_ids})),
            prerequisites=tuple(sorted(prerequisites)),mandatory=any(g.mandatory for g in members),
            priority=min(g.priority for g in members),distance=min(g.distance for g in members)))
    return result
