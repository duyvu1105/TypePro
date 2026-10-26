"""Versioned evidence data. Structural graphs never contain annotation evidence."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import PurePosixPath

POLICY = 'graph-context-v1'
SCHEMA = 'typepro-evidence-graph-v1'
MASKING = 'graph-target-overlay-v1'
OUTCOMES = {'ready', 'unresolved', 'budget_exceeded', 'parse_error', 'target_not_found', 'timeout'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class TargetSpec:
    project: str
    file: str
    function: str
    scope: str
    name: str
    occurrence: int | None = None
    record_id: str = ''

    def __post_init__(self):
        if self.scope not in {'arg', 'return'} or (self.occurrence is not None and self.occurrence < 0):
            raise ValueError('Graph targets require arg/return scope and nonnegative occurrence')
        if PurePosixPath(self.file).is_absolute() or '..' in PurePosixPath(self.file).parts or '..' in PurePosixPath(self.project).parts:
            raise ValueError('Target source identity must stay inside its project')

    @property
    def identity(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class Span:
    file: str
    start: int
    end: int
    column: int = 0


@dataclass(frozen=True)
class Node:
    id: str
    kind: str
    scope: str
    span: Span
    source_hash: str
    text: str
    symbol: str = ''


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: str
    rule: str
    certainty: str = 'may'

    @property
    def id(self):
        return digest(asdict(self))


@dataclass
class EvidenceGraph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: set[Edge] = field(default_factory=set)
    gaps: list[dict] = field(default_factory=list)
    seeds: set[str] = field(default_factory=set)

    def link(self, source, target, kind, rule, certainty='may'):
        if source not in self.nodes or target not in self.nodes:
            raise ValueError('Broken evidence edge')
        self.edges.add(Edge(source, target, kind, rule, certainty))

    def gap(self, node, reason, possible_bindings=()):
        original = self.nodes[node]
        unresolved_id = digest(('unresolved', node, reason))
        self.nodes[unresolved_id] = Node(unresolved_id, 'unresolved', original.scope,
            original.span, original.source_hash, original.text, reason)
        self.link(node, unresolved_id, 'unresolved', reason)
        value = dict(node=node, unresolved_node=unresolved_id, reason=reason, possible_bindings=sorted(possible_bindings))
        if value not in self.gaps:
            self.gaps.append(value)

    def serialize(self):
        return dict(schema=SCHEMA, nodes=[asdict(self.nodes[k]) for k in sorted(self.nodes)],
                    edges=[dict(asdict(e), id=e.id) for e in sorted(self.edges, key=lambda e: e.id)],
                    gaps=sorted(self.gaps, key=lambda g: (g['node'], g['reason'])), seeds=sorted(self.seeds))
