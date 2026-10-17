"""Candidate scores and character budgets; never reads labels or tokenizers."""
from __future__ import annotations

import ast
import copy
import re
from difflib import SequenceMatcher
from functools import lru_cache

from typepro.analysis.ast_context_slicer import (
    FUNCTIONS,
    bind_arguments,
    lexical_nodes,
    limit_candidate_definition,
    static_body,
)
from typepro.analysis.BM25 import bm25_similarity
from typepro.analysis.signature_contracts import imported_name, opaque

POLICY = 'candidate-weighted-v1'
WEIGHTS = {'direct': 5.0, 'usage': 3.0, 'bm25': 2.0, 'name': 1.0, 'import': 0.5}
MIN_SCORE = 1.0
MAX_CANDIDATES = 10
TOTAL_CHARS = 16000
DEFINITION_CHARS = 4000
SUMMARY_CHARS = 600
HEADER = '[RECOMMENDATION_TYPES]'
STOP_WORDS = {
    'and', 'as', 'async', 'await', 'class', 'def', 'else', 'false', 'for',
    'from', 'if', 'import', 'in', 'none', 'not', 'or', 'pass', 'return',
    'self', 'true', 'with', 'yield',
}


def _structural_text(text):
    return ' '.join(t.casefold() for t in re.findall(r'[A-Za-z_]\w*', text)
                    if t.casefold() not in STOP_WORDS)


_cached_structural_text = lru_cache(maxsize=256)(_structural_text)


def structural_text(text):
    # Cache by exact masked content, never by a candidate name or KB identity.
    return _cached_structural_text(text) if len(text) <= 32768 else _structural_text(text)


def _definition_members(definition):
    available = set()
    try:
        tree = ast.parse(definition.replace('<mask>', '__TYPEPRO_TARGET_MASK__'))
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            available.update(n.name for n in cls.body if isinstance(n, FUNCTIONS))
            available.update(n.attr for n in ast.walk(cls) if isinstance(n, ast.Attribute)
                             and isinstance(n.ctx, ast.Store) and isinstance(n.value, ast.Name)
                             and n.value.id in {'self', 'cls'})
    except (SyntaxError, ValueError):
        pass
    return frozenset(available)


_cached_definition_members = lru_cache(maxsize=128)(_definition_members)


def score_candidate(item, definition, target_name, code_slice, members, evidence, *, query_text=None):
    """Five components in [0, 1]; seed position gives no points."""
    qualified = str(item.get('qualified_name') or item['name'])
    wanted = set((members or {}).get('methods', ())) | set((members or {}).get('attributes', ()))
    available = set(item.get('members', ()))
    if wanted and not available:
        available.update(_cached_definition_members(definition) if len(definition) <= 32768
                         else _definition_members(definition))
    compact = lambda value: re.sub(r'[^a-z0-9]', '', value.casefold())
    left, right = compact(target_name), compact(str(item['name']))
    if query_text is None:
        query_text = structural_text(code_slice)
    document_text = structural_text(definition)
    components = {
        'direct': float(qualified in evidence.get('direct', ())),
        'usage': len(wanted & available) / len(wanted) if wanted else 0.0,
        'bm25': bm25_similarity(query_text, document_text) if query_text and document_text else 0.0,
        'name': SequenceMatcher(None, left, right).ratio() if left and right else 0.0,
        'import': float(qualified in evidence.get('import', ())),
    }
    score = sum(WEIGHTS[key] * value for key, value in components.items())
    return score, components


def source_evidence(catalog, file_path, function, target_name, target_scope, records):
    """Resolve constructors at verified calls; annotations are never inspected.

    Ambiguous bindings, dynamic effects, local imports and unknown receivers do
    not receive direct/import points. They can still rank by BM25/name/usage.
    """
    evidence = {'direct': set(), 'import': set()}
    if catalog is None or function is None:
        return evidence
    from pathlib import Path
    path = str(Path(file_path).resolve())
    if path not in catalog.trees:
        return evidence
    identities = {str(r.get('qualified_name') or r['name']) for r in records}
    opaque_scopes = {}

    def identity(expression, source_path, scope):
        key = (source_path, id(scope))
        if key not in opaque_scopes:
            opaque_scopes[key] = opaque(catalog, source_path, scope)
        if opaque_scopes[key]:
            return None
        root = expression
        while isinstance(root, ast.Attribute):
            root = root.value
        if not isinstance(root, ast.Name):
            return None
        if isinstance(scope, FUNCTIONS) and catalog.bindings(scope, root.id):
            return None
        if isinstance(scope, ast.Module):
            bindings = catalog.module_bindings(source_path, root.id)
            if len(bindings) != 1:
                return None
            statement = bindings[0][0] if isinstance(bindings[0], tuple) else bindings[0]
            if getattr(statement, 'lineno', 0) >= getattr(expression, 'lineno', float('inf')):
                return None
        qualified = imported_name(catalog, source_path, expression)
        if qualified:
            return qualified if qualified in identities else None
        bindings = catalog.module_bindings(source_path, root.id)
        if isinstance(expression, ast.Name) and len(bindings) == 1:
            node = bindings[0]
            if isinstance(node, ast.ClassDef) and node in catalog.module_bodies[source_path]:
                module = catalog.modules[source_path] or Path(source_path).stem
                qualified = '.'.join(filter(None, (module, node.name)))
                if qualified in identities:
                    return qualified
                # Legacy file-local seed records can carry an unqualified name.
                return node.name if node.name in identities else None
        return None

    # Only explicit, unshadowed module imports in the target's scope count.
    for statement in catalog.module_bodies[path]:
        if not isinstance(statement, (ast.Import, ast.ImportFrom)):
            continue
        for alias in statement.names:
            if alias.name == '*':
                continue
            local = alias.asname or (alias.name if isinstance(statement, ast.ImportFrom)
                                     else alias.name.split('.')[0])
            for qualified in identities:
                if isinstance(statement, ast.ImportFrom):
                    module = catalog.import_module(path, statement)
                    if not module or qualified != f'{module}.{alias.name}':
                        continue
                    spelling = local
                else:
                    if not qualified.startswith(alias.name + '.'):
                        continue
                    spelling = ((local + qualified[len(alias.name):]) if alias.asname else qualified)
                expression = ast.parse(spelling, mode='eval').body
                if identity(expression, path, function) == qualified:
                    evidence['import'].add(qualified)

    def construction(value, source_path, scope, before_line, depth=0):
        if depth >= 4:
            return None
        if value is None:
            return None
        if isinstance(value, ast.Name):
            bindings = (catalog.bindings(scope, value.id) if isinstance(scope, FUNCTIONS)
                        else catalog.module_bindings(source_path, value.id))
            if len(bindings) != 1 or not isinstance(bindings[0], ast.Name):
                return None
            # Single unconditional assignment before the call; no alias guessing.
            assignments = [s for s in static_body(scope.body)
                           if isinstance(s, (ast.Assign, ast.AnnAssign)) and s.lineno < before_line
                           and any(n is bindings[0] for n in ast.walk(s))]
            if len(assignments) != 1:
                return None
            value = assignments[0].value
        if not isinstance(value, ast.Call):
            return None
        qualified = identity(value.func, source_path, scope)
        if qualified:
            return qualified
        # Follow a verified zero-argument factory, never its return annotation.
        record, _ = catalog.resolve(value, source_path, scope)
        if record is None:
            return None
        factory_path, _, factory, *_ = record
        if (factory.args.posonlyargs or factory.args.args or factory.args.kwonlyargs
                or factory.args.vararg or factory.args.kwarg):
            return None
        returns = [n for n in lexical_nodes(factory) if isinstance(n, ast.Return)]
        outputs = {construction(n.value, factory_path, factory, n.lineno, depth + 1) for n in returns}
        return next(iter(outputs)) if len(outputs) == 1 and None not in outputs else None

    if target_scope == 'return':
        for node in lexical_nodes(function):
            if isinstance(node, ast.Return):
                qualified = construction(node.value, path, function, node.lineno)
                if qualified:
                    evidence['direct'].add(qualified)
    elif target_scope == 'arg':
        matches = [r for r in catalog.records if r[0] == path and r[2].lineno == function.lineno
                   and r[2].name == function.name]
        if len(matches) == 1:
            for caller_path, caller, call in catalog.callers(matches[0][1]):
                bound, _ = bind_arguments(function, call)
                if bound is None:
                    continue
                value = bound.get(target_name)
                # Default expressions belong to the callee's declaration scope.
                # Only explicitly supplied arguments are handled here.
                if value is None or not any(n is value for n in ast.walk(call)):
                    continue
                qualified = construction(value, caller_path, caller, call.lineno)
                if qualified:
                    evidence['direct'].add(qualified)
    return evidence


def candidate_block(item, definition=None):
    name = item.get('type') or item.get('name')
    qualified = item.get('qualified_name') or name
    text = item['definition'] if definition is None else definition
    return f'[TYPE] {name}\n[QUALIFIED_NAME] {qualified}\n[DEFINITION]\n{text}'


def candidate_section(items):
    return '\n'.join([HEADER, *(candidate_block(item) for item in items)])


def _fit_definition(definition, maximum):
    """Use whole declarations; an impossible header drops the candidate."""
    if maximum <= 0:
        return ''
    summary_limit = maximum
    try:
        ast.parse(definition.replace('<mask>', '__TYPEPRO_TARGET_MASK__'))
    except (SyntaxError, ValueError, RecursionError):
        # Small imported signature lists also need complete method suites.
        summary_limit = min(maximum, max(1, len(definition) - 1))
    text, _ = limit_candidate_definition(definition, maximum=summary_limit)
    if not text or len(text) > maximum or text.startswith('# candidate definition omitted:'):
        return ''
    # Restore whole method bodies when they fit after the signature summary.
    if len(definition) > maximum:
        try:
            original = ast.parse(definition.replace('<mask>', '__TYPEPRO_TARGET_MASK__'))
            summary = ast.parse(text.replace('<mask>', '__TYPEPRO_TARGET_MASK__'))
            for full_class, short_class in zip(original.body, summary.body):
                if not isinstance(full_class, ast.ClassDef) or not isinstance(short_class, ast.ClassDef):
                    continue
                methods = {n.name: n for n in full_class.body if isinstance(n, FUNCTIONS)}
                for index, node in enumerate(short_class.body):
                    if not isinstance(node, FUNCTIONS) or node.name not in methods:
                        continue
                    short_class.body[index] = methods[node.name]
                    trial = ast.unparse(summary).replace('__TYPEPRO_TARGET_MASK__', '<mask>')
                    if len(trial) <= maximum:
                        text = trial
                    else:
                        short_class.body[index] = node
        except (SyntaxError, ValueError):
            pass
    return text


_cached_fit_definition = lru_cache(maxsize=256)(_fit_definition)


def fit_definition(definition, maximum):
    # Only immutable rendered strings are shared; parsed ASTs stay private.
    if len(definition) <= 32768:
        return _cached_fit_definition(definition, maximum)
    return _fit_definition(definition, maximum)


def allocate_characters(items):
    """Reserve <=600 chars/item, then weighted water-filling up to 4000/definition."""
    prepared = []
    for original in items[:MAX_CANDIDATES]:
        item = copy.deepcopy(original)
        item['_original_chars'] = len(item['definition'])
        full = fit_definition(item['definition'], DEFINITION_CHARS)
        overhead = len(candidate_block(item, ''))
        base = fit_definition(full, SUMMARY_CHARS - overhead) if full else ''
        if not base:
            continue
        item['_full'], item['_base'] = full, base
        item['_capacity'] = len(full) - len(base)
        item['_extra'] = 0
        prepared.append(item)
    remaining = TOTAL_CHARS - len(HEADER) - sum(
        1 + len(candidate_block(item, item['_base'])) for item in prepared)
    while remaining > 0:
        active = [item for item in prepared if item['_extra'] < item['_capacity']]
        if not active:
            break
        weights = [max(float(item.get('score', 1.0)), MIN_SCORE) for item in active]
        total = sum(weights)
        shares = [min(item['_capacity'] - item['_extra'], int(remaining * weight / total))
                  for item, weight in zip(active, weights)]
        if not any(shares):
            shares[0] = 1  # Stable rounding: ranking order wins the leftover.
        for item, amount in zip(active, shares):
            item['_extra'] += amount
            remaining -= amount
    full_definitions = [item['_full'] for item in prepared]
    result = []
    for item in prepared:
        maximum = len(item['_base']) + item['_extra']
        text = fit_definition(item['_full'], maximum) or item['_base']
        item['definition'] = text
        reduction = item.setdefault('definition_reduction', {})
        reduction.update(output_chars=len(text), max_chars=DEFINITION_CHARS,
                         mode='full' if len(text) == item['_original_chars'] else 'character_summary')
        item['character_budget'] = {
            'summary_chars': len(candidate_block(item, item['_base'])),
            'definition_budget': maximum, 'output_chars': len(text),
            'original_chars': item['_original_chars'],
            'truncated': len(text) < item['_original_chars'],
        }
        for key in ('_full', '_base', '_capacity', '_extra', '_original_chars'):
            del item[key]
        result.append(item)
    assert len(candidate_section(result)) <= TOTAL_CHARS
    # Whole declarations may leave gaps. Offer that space to other candidates.
    for _ in range(MAX_CANDIDATES):
        spare = TOTAL_CHARS - len(candidate_section(result))
        active = [(item, full) for item, full in zip(result, full_definitions)
                  if len(item['definition']) < len(full)]
        if not spare or not active:
            break
        changed = False
        total_weight = sum(max(float(item.get('score', 1)), MIN_SCORE) for item, _ in active)
        for item, full in active:
            share = int(spare * max(float(item.get('score', 1)), MIN_SCORE) / total_weight)
            maximum = min(DEFINITION_CHARS, len(item['definition']) + share)
            trial = fit_definition(full, maximum)
            if len(trial) > len(item['definition']):
                item['definition'] = trial
                item['character_budget'].update(output_chars=len(trial), definition_budget=maximum)
                item['character_budget']['truncated'] = len(trial) < item['character_budget']['original_chars']
                item['definition_reduction']['output_chars'] = len(trial)
                changed = True
        if not changed:
            break
    assert len(candidate_section(result)) <= TOTAL_CHARS
    return result
