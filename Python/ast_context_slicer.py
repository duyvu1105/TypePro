"""Conservative, non-executing AST context reduction.

Blocks are reduced recursively. This selects type evidence, not an executable
program transformation; unknown dynamic scope effects are reported explicitly.
"""
from __future__ import annotations

import ast
import copy
from dataclasses import dataclass, field
from pathlib import Path

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
POLICY = 'ast-context-v7-verified-signature-evidence'
CANDIDATE_DEFINITION_MAX_CHARS = 8000


def static_body(body):
    """Flatten only literal boolean branches; never evaluate project code."""
    for statement in body:
        if isinstance(statement, ast.If) and isinstance(statement.test, ast.Constant) and type(statement.test.value) is bool:
            yield from static_body(statement.body if statement.test.value else statement.orelse)
        else:
            yield statement


def names(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def body_names(node):
    """Annotations do not participate in dependency decisions."""
    node = ast.parse(ast.unparse(node))
    for child in ast.walk(node):
        if isinstance(child, ast.AnnAssign):
            child.annotation = ast.Constant(None)
        elif isinstance(child, ast.arg):
            child.annotation = None
        elif isinstance(child, FUNCTIONS):
            child.returns = None
    return names(node)


def effect_reason(node):
    for child in ast.walk(node):
        if isinstance(child, (ast.Global, ast.Nonlocal, ast.ClassDef, *FUNCTIONS)):
            return 'unsupported_scope_effect'
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id in {
            'exec', 'eval', 'locals', 'globals', 'vars', 'getattr', 'setattr', 'delattr',
        }:
            return 'dynamic_effect'
    return ''


@dataclass
class Reduction:
    node: ast.AST
    mode: str
    reason: str
    before: int
    after: int
    evidence: list = field(default_factory=list)

    def diagnostics(self):
        return dict(mode=self.mode, reason=self.reason, before=self.before, after=self.after,
                    retained_evidence=self.evidence)


def reduce_function(function, parameters=(), returns=False, *, seed_calls=(), include_exits=True):
    """Select evidence recursively, keeping enclosing control dependencies.

    Target exits are preserved by default. Parameter-only callee supplements
    can disable exit seeds; callers seed the exact resolved call instead.
    """
    return _reduce_recursive(function, parameters, returns, seed_calls, include_exits)


def data_names(node):
    """Value and callable dependencies, excluding annotation labels."""
    found = set()
    def visit(child):
        if isinstance(child, ast.Name):
            found.add(child.id)
        for field, value in ast.iter_fields(child):
            if field in {'annotation', 'returns'}:
                continue
            if isinstance(value, ast.AST):
                visit(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        visit(item)
    visit(node)
    return found


def lexical_nodes(scope):
    """Walk one execution scope; nested callable bodies have their own bindings."""
    def visit(node):
        yield node
        if node is not scope and isinstance(node, (*FUNCTIONS, ast.ClassDef, ast.Lambda)):
            return
        for child in ast.iter_child_nodes(node):
            yield from visit(child)
    yield from visit(scope)


def collection_evidence(function, roots):
    """Identify operations on aliases/elements without leaking loop bindings.

    Reassignment kills an element relation. Branches join conservatively; the
    relations select evidence, and never assert a concrete inferred type.
    """
    evidence, stale_names = set(), {}
    def walk(body, related, stale=frozenset()):
        related = set(related)
        stale = set(stale)
        for statement in body:
            stale_names[id(statement)] = set(stale)
            if isinstance(statement, (*FUNCTIONS, ast.ClassDef)):
                related.discard(statement.name)
                continue
            if isinstance(statement, (ast.For, ast.AsyncFor)):
                inner = related - data_names(statement.target)
                if data_names(statement.iter) & related:
                    inner.update(data_names(statement.target))
                walk(statement.body, inner, stale - data_names(statement.target))
                walk(statement.orelse, related, stale)
                # The loop can run zero times; do not export its element alias.
                related.difference_update(data_names(statement.target))
                continue
            child_bodies = [v for _, v in ast.iter_fields(statement)
                            if isinstance(v, list) and v and all(isinstance(s, ast.stmt) for s in v)]
            if child_bodies:
                joined = set(related)
                for body_part in child_bodies:
                    joined.update(walk(body_part, related, stale))
                if isinstance(statement, ast.Try):
                    for handler in statement.handlers:
                        joined.update(walk(handler.body, related, stale))
                if isinstance(statement, ast.Match):
                    for case in statement.cases:
                        joined.update(walk(case.body, related, stale))
                related = joined
                continue
            local = list(lexical_nodes(statement))
            if any(isinstance(n, (ast.Attribute, ast.Subscript)) and data_names(n.value) & related for n in local):
                evidence.add(id(statement))
            # A call receiving a relevant element can mutate it. Unknown effects
            # preserve the call; no guessed callee body is inserted.
            if any(isinstance(n, ast.Call) and any(data_names(v) & related
                   for v in [*n.args, *(k.value for k in n.keywords)]) for n in local):
                evidence.add(id(statement))
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                written = {n.id for t in targets for n in ast.walk(t)
                           if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
                alias = statement.value is not None and isinstance(statement.value, (ast.Name, ast.Subscript)) and data_names(statement.value) & related
                if not alias:
                    stale.update((written & related) - set(roots))
                    stale_names[id(statement)].update((written & related) - set(roots))
                related.difference_update(written - set(roots))
                if alias:
                    related.update(written)
                    stale.difference_update(written)
            elif isinstance(statement, (ast.AugAssign, ast.Delete)):
                related.difference_update(n.id for n in local if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)))
        return related
    walk(function.body, roots)
    return evidence, stale_names


def docstring_statement(function):
    """Return only the leading docstring, never arbitrary string expressions."""
    return function.body[:1] if ast.get_docstring(function, clean=False) is not None else []


def limit_candidate_definition(definition):
    """Keep small definitions verbatim; summarize large ones without cutting code.

    Signatures take priority over complete docstring paragraphs. If signatures
    alone exceed the budget, omit whole declarations from the end. Shared KB
    definitions and ranking inputs are never modified.
    """
    import re
    maximum = CANDIDATE_DEFINITION_MAX_CHARS
    if len(definition) <= maximum:
        return definition, {'mode': 'full', 'docstrings_shortened': False, 'omitted_declarations': 0}
    display_mask = '<mask>' in definition
    source = definition.replace('<mask>', '__TYPEPRO_TARGET_MASK__')
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        # Imported KB records can be signature lists with deliberately empty
        # method suites. Supply pass only for complete one-line headers.
        lines = source.splitlines()
        repaired = []
        for index, line in enumerate(lines):
            repaired.append(line)
            stripped = line.lstrip()
            if stripped.startswith(('def ', 'async def ', 'class ')) and stripped.endswith(':'):
                indent = len(line) - len(stripped)
                following = next((s for s in lines[index + 1:]
                                  if s.strip() and not s.lstrip().startswith('#')), '')
                if not following or len(following) - len(following.lstrip()) <= indent:
                    repaired.append(' ' * (indent + 4) + 'pass')
        try:
            tree = ast.parse('\n'.join(repaired))
        except (SyntaxError, ValueError, RecursionError):
            return '# candidate definition omitted: unparseable source', {
                'mode': 'omitted', 'reason': 'parse_error', 'docstrings_shortened': False,
                'omitted_declarations': 0}
    documents = []
    def summarize(node):
        if isinstance(node, (*FUNCTIONS, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                documents.append((node, doc))
            if isinstance(node, FUNCTIONS):
                node.body = [ast.Pass()]
            else:
                node.body = [summarize(s) for s in node.body
                             if isinstance(s, (*FUNCTIONS, ast.ClassDef, ast.Assign, ast.AnnAssign))] or [ast.Pass()]
        elif isinstance(node, ast.AnnAssign):
            node.value = None
        elif isinstance(node, ast.Assign):
            node.value = ast.Constant(Ellipsis)
        return node
    tree.body = [summarize(s) for s in tree.body
                 if isinstance(s, (*FUNCTIONS, ast.ClassDef, ast.Assign, ast.AnnAssign))]
    def render():
        text = ast.unparse(ast.fix_missing_locations(tree))
        return text.replace('__TYPEPRO_TARGET_MASK__', '<mask>') if display_mask else text
    text = render()
    omitted = 0
    while len(text) > maximum:
        # Drop complete trailing class members before dropping a class header.
        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)
                   and not (len(n.body) == 1 and isinstance(n.body[0], ast.Pass))]
        if classes:
            owner = classes[-1]
            count = max(1, int(len(owner.body) * (1 - maximum / len(text))))
            del owner.body[-count:]
            if not owner.body:
                owner.body = [ast.Pass()]
        elif tree.body:
            count = 1
            tree.body.pop()
        omitted += count
        text = render()
    retained = {id(n) for n in ast.walk(tree)}
    shortened = False
    for owner, document in documents:
        if id(owner) not in retained:
            continue
        paragraphs = re.split(r'\n\s*\n', document)
        kept = []
        for paragraph in paragraphs:
            trial = '\n\n'.join([*kept, paragraph])
            owner.body.insert(0, ast.Expr(value=ast.Constant(trial)))
            trial_text = render()
            owner.body.pop(0)
            if len(trial_text) > maximum:
                break
            kept.append(paragraph)
        if kept:
            owner.body.insert(0, ast.Expr(value=ast.Constant('\n\n'.join(kept))))
        shortened |= len(kept) != len(paragraphs)
    text = render() or '# candidate definition omitted: signatures exceed character budget'
    ast.parse(text.replace('<mask>', '__TYPEPRO_TARGET_MASK__'))
    return text, {'mode': 'signature_docstring', 'docstrings_shortened': shortened,
                  'omitted_declarations': omitted}


def _reduce_recursive(function, parameters, returns, seed_calls, include_exits):
    result = ast.parse(ast.unparse(function)).body[0]
    before = sum(isinstance(n, ast.stmt) for s in function.body for n in ast.walk(s))
    for statement in function.body:
        reason = effect_reason(statement)
        if reason:
            return Reduction(result, 'full_fallback', reason, before, before)
    # Work with original identities, then copy only selected statements.
    nodes, parents, headers = [], {}, {}
    def collect(body, ancestors=()):
        for statement in body:
            nodes.append(statement)
            parents[id(statement)] = ancestors
            lists = []
            header = copy.copy(statement)
            for field, value in ast.iter_fields(statement):
                if isinstance(value, list) and value and all(isinstance(x, ast.stmt) for x in value):
                    lists.append(value)
                    setattr(header, field, [])
            if isinstance(statement, (ast.Try, getattr(ast, 'TryStar', ast.Try))):
                header.handlers = []
                for handler in statement.handlers:
                    # Handler type/name are dependencies when its body survives.
                    collect(handler.body, (*ancestors, statement))
            if isinstance(statement, ast.Match):
                header.cases = []
                for case in statement.cases:
                    collect(case.body, (*ancestors, statement))
            headers[id(statement)] = header
            for child_body in lists:
                collect(child_body, (*ancestors, statement))
    collect(function.body)
    compound = {id(s) for ancestors in parents.values() for s in ancestors}
    references = {id(s): data_names(headers[id(s)]) for s in nodes}
    writes, receivers = {}, {}
    flow = set(parameters)
    for s in nodes:
        header = headers[id(s)]
        writes[id(s)] = {n.id for n in ast.walk(header) if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))}
        receivers[id(s)] = set().union(*(data_names(n.value) for n in ast.walk(header)
            if isinstance(n, (ast.Attribute, ast.Subscript))))
    changed = True
    while changed:
        previous = set(flow)
        for s in nodes:
            if isinstance(s, (ast.Assign, ast.AnnAssign)) and s.value is not None and data_names(s.value) & flow:
                flow.update(writes[id(s)])
            elif isinstance(s, (ast.For, ast.AsyncFor)) and data_names(s.iter) & flow:
                flow.update(data_names(s.target))
            elif isinstance(s, (ast.With, ast.AsyncWith)):
                for item in s.items:
                    if data_names(item.context_expr) & flow and item.optional_vars is not None:
                        flow.update(data_names(item.optional_vars))
            elif isinstance(s, ast.Match) and data_names(s.subject) & flow:
                flow.update(n.name for case in s.cases for n in ast.walk(case.pattern)
                            if isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name)
        changed = previous != flow
    selected, live = set(), set(parameters)
    seeds = {id(call) for call in seed_calls}
    effect_objects = set(parameters)
    for call in seed_calls:
        for value in [*call.args, *(k.value for k in call.keywords)]:
            effect_objects.update(data_names(value))
    if returns or (include_exits and not seeds):
        for s in nodes:
            if isinstance(s, (ast.Return, ast.Yield, ast.YieldFrom)) and s.value is not None:
                effect_objects.update(data_names(s.value))
    changed = True
    while changed:
        previous = set(effect_objects)
        for s in nodes:
            if isinstance(s, (ast.Assign, ast.AnnAssign)) and isinstance(s.value, ast.Name) and s.value.id in effect_objects:
                effect_objects.update(writes[id(s)])
            if isinstance(s, (ast.Assign, ast.AnnAssign)) and isinstance(s.value, ast.Name) and writes[id(s)] & effect_objects:
                effect_objects.add(s.value.id)
        changed = previous != effect_objects
    collection_statements, stale_names = collection_evidence(function, effect_objects)
    def choose(statement):
        selected.add(id(statement))
        live.update(references[id(statement)])
        for parent in parents[id(statement)]:
            selected.add(id(parent))
            live.update(references[id(parent)])
            if isinstance(parent, ast.Try):
                for handler in parent.handlers:
                    if handler.type is not None:
                        live.update(data_names(handler.type))
            if isinstance(parent, ast.Match):
                for case in parent.cases:
                    live.update(data_names(case.pattern))
                    if case.guard is not None:
                        live.update(data_names(case.guard))
    for statement in nodes:
        if id(statement) in compound:
            if references[id(statement)] & flow:
                choose(statement)
            continue
        has_exit = any(isinstance(n, (ast.Return, ast.Raise, ast.Yield, ast.YieldFrom)) for n in ast.walk(statement))
        early_exit = seeds and isinstance(statement, (ast.Return, ast.Raise)) and statement.lineno <= max(call.lineno for call in seed_calls)
        if (not seeds and (include_exits or returns) and has_exit) or early_exit or any(id(n) in seeds for n in ast.walk(statement)):
            choose(statement)
    if not live and not selected:
        return Reduction(result, 'full_fallback', 'no_dependency_seed', before, before)
    while True:
        previous = (len(selected), len(live))
        for statement in nodes:
            if id(statement) in compound:
                continue
            stale = stale_names.get(id(statement), set())
            ref = references[id(statement)] - stale
            # Preserve loop exits and early function exits affecting selected
            # evidence, but never retain an unrelated block just for its header.
            transfer = isinstance(statement, (ast.Break, ast.Continue, ast.Return, ast.Raise))
            affects_control = transfer and any(id(p) in selected for p in parents[id(statement)])
            possible_mutation = any(isinstance(n, ast.Call) and any(data_names(v) & effect_objects
                for v in [*n.args, *(k.value for k in n.keywords)]) for n in ast.walk(statement))
            if ref & flow or (writes[id(statement)] - stale) & live or (receivers[id(statement)] - stale) & live or affects_control or possible_mutation or id(statement) in collection_statements:
                choose(statement)
        if previous == (len(selected), len(live)):
            break
    def render(body):
        output = []
        for statement in body:
            if id(statement) not in selected:
                continue
            cloned = copy.copy(statement)
            for field, value in ast.iter_fields(statement):
                if isinstance(value, list) and value and all(isinstance(x, ast.stmt) for x in value):
                    setattr(cloned, field, render(value) or ([ast.Pass()] if field == 'body' else []))
            if isinstance(statement, (ast.Try, getattr(ast, 'TryStar', ast.Try))):
                cloned.handlers = [copy.copy(h) for h in statement.handlers]
                for original, handler in zip(statement.handlers, cloned.handlers):
                    handler.body = render(original.body) or [ast.Pass()]
                if not cloned.handlers and not cloned.finalbody:
                    cloned.finalbody = [ast.Pass()]
            if isinstance(statement, ast.Match):
                cloned.cases = [copy.copy(c) for c in statement.cases]
                for original, case in zip(statement.cases, cloned.cases):
                    case.body = render(original.body) or [ast.Pass()]
            output.append(cloned)
        return output
    result.body = [*copy.deepcopy(docstring_statement(function)), *render(function.body)] or [ast.Pass()]
    ast.fix_missing_locations(result)
    ast.parse(ast.unparse(result))
    after = sum(isinstance(n, ast.stmt) for s in result.body for n in ast.walk(s))
    evidence = [dict(kind='collection_operation', source_line=s.lineno,
                     reason='operation_on_relevant_collection_or_element')
                for s in nodes if id(s) in collection_statements and id(s) in selected]
    return Reduction(result, 'sliced', '', before, after, evidence)


def bind_arguments(function, call):
    """Bind a plain, resolved function call. Unknown expansions fail closed."""
    args = []
    for value in call.args:
        if isinstance(value, ast.Starred):
            if not isinstance(value.value, (ast.Tuple, ast.List)) or any(
                isinstance(v, ast.Starred) for v in value.value.elts
            ):
                return None, 'unresolved_argument_binding'
            args.extend(value.value.elts)
        else:
            args.append(value)
    keywords = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            value = keyword.value
            if not isinstance(value, ast.Dict) or any(
                not isinstance(k, ast.Constant) or not isinstance(k.value, str) for k in value.keys
            ):
                return None, 'unresolved_argument_binding'
            # Duplicate literals are legal at dict construction, but could
            # hide which evidence wins: fallback rather than guess.
            pairs = [(k.value, v) for k, v in zip(value.keys, value.values)]
        else:
            pairs = [(keyword.arg, keyword.value)]
        for key, value in pairs:
            if key in keywords:
                return None, 'invalid_binding'
            keywords[key] = value
    signature = function.args
    if signature.vararg or signature.kwarg:
        return None, 'unresolved_variadic_binding'
    positional = [*signature.posonlyargs, *signature.args]
    if len(args) > len(positional):
        return None, 'invalid_binding'
    bound = {p.arg: v for p, v in zip(positional, args)}
    allowed = {p.arg for p in [*signature.args, *signature.kwonlyargs]}
    for key, value in keywords.items():
        if key not in allowed or key in bound:
            return None, 'invalid_binding'
        bound[key] = value
    defaults = dict(zip([p.arg for p in positional[len(positional) - len(signature.defaults):]], signature.defaults))
    defaults.update({p.arg: d for p, d in zip(signature.kwonlyargs, signature.kw_defaults) if d is not None})
    for parameter in [*positional, *signature.kwonlyargs]:
        if parameter.arg not in bound:
            if parameter.arg not in defaults:
                return None, 'invalid_binding'
            bound[parameter.arg] = defaults[parameter.arg]
    return bound, ''


class FunctionCatalog:
    """Read-only sidecar over the project's already parsed ASTs."""
    def __init__(self, parsed_files, project_root=None):
        from project_index import project_module_aliases
        self.module_aliases = project_module_aliases(Path(project_root)) if project_root else {}
        self.records = []
        self.trees = {}
        self.modules = {}
        self.by_module = {}
        self.module_bodies = {}
        self.callers_cache = None
        self.caller_rejections = {}
        self.nested_scopes = set()
        for path, module, source, tree in parsed_files:
            path = str(Path(path).resolve())
            self.trees[path] = tree
            self.module_bodies[path] = tuple(static_body(tree.body))
            self.modules[path] = module
            self.by_module.setdefault(module, []).append(path)
            def visit(body, scopes=(), function_depth=0):
                for node in static_body(body):
                    if isinstance(node, FUNCTIONS):
                        qualified = '.'.join(filter(None, (module, *scopes, node.name)))
                        self.records.append((path, qualified, node, bool(scopes)))
                        if function_depth:
                            self.nested_scopes.add((path, node.lineno, node.name))
                        visit(node.body, (*scopes, node.name), function_depth + 1)
                    elif isinstance(node, ast.ClassDef):
                        visit(node.body, (*scopes, node.name), function_depth)
            visit(tree.body)
        self.by_identity = {}
        self.scope_records = {}
        self.binding_cache = {}
        self.module_binding_cache = {}
        self.alias_cache = {}
        for record in self.records:
            self.by_identity.setdefault((record[0], record[1]), []).append(record)
            self.scope_records.setdefault((record[0], record[2].lineno, record[2].name), []).append(record)

    def bindings(self, tree, name):
        key = (id(tree), name)
        if key not in self.binding_cache:
            self.binding_cache[key] = self._bindings(tree, name)
        return self.binding_cache[key]

    def import_module(self, path, statement):
        module = statement.module or ''
        if statement.level:
            package = self.modules[path].split('.')
            if Path(path).name != '__init__.py':
                package = package[:-1]
            if statement.level > len(package):
                return None
            module = '.'.join(package[:len(package) - statement.level + 1] + ([module] if module else []))
        return self.canonical_module(module)

    def canonical_module(self, qualified):
        for alias in sorted(self.module_aliases, key=len, reverse=True):
            if qualified == alias or qualified.startswith(alias + '.'):
                return self.module_aliases[alias] + qualified[len(alias):]
        return qualified

    def imported_function(self, qualified, seen=frozenset()):
        """Follow explicit re-exports without expanding any function body."""
        qualified = self.canonical_module(qualified)
        if qualified in seen or len(seen) >= 32:
            return [], 'import_cycle', []
        module, _, name = qualified.rpartition('.')
        paths = self.by_module.get(module, ())
        if len(paths) != 1:
            return [], 'ambiguous_import_module', []
        path = paths[0]
        bindings = self.module_bindings(path, name)
        if not bindings or len(bindings) != 1:
            return [], 'rebound_imported_function', [path]
        binding = bindings[0]
        if isinstance(binding, FUNCTIONS) and binding in self.module_bodies[path]:
            matches = [r for r in self.by_identity.get((path, qualified), ()) if not r[3]]
            return matches, '', [path]
        if isinstance(binding, tuple):
            statement, alias = binding
            if isinstance(statement, ast.ImportFrom) and statement in self.module_bodies[path] and alias.name != '*':
                origin = self.import_module(path, statement)
                matches, reason, traversed = self.imported_function('.'.join(filter(None, (origin, alias.name))), seen | {qualified})
                return matches, reason, [path, *traversed]
        return [], 'ambiguous_or_missing_definition', [path]

    def alias_declaration(self, path, name, seen=frozenset()):
        from type_aliases import declared_aliases
        key = (path, name)
        if key in seen:
            return None
        tree = self.trees[path]
        if path not in self.alias_cache:
            self.alias_cache[path] = {n: (node, value) for n, value, node, _ in declared_aliases(tree)}
        if name in self.alias_cache[path]:
            node, value = self.alias_cache[path][name]
            return path, name, node, value
        bindings = self.module_bindings(path, name)
        if len(bindings or ()) == 1 and isinstance(bindings[0], tuple):
            statement, alias = bindings[0]
            if isinstance(statement, ast.ImportFrom) and statement in self.module_bodies[path] and alias.name != '*':
                paths = self.by_module.get(self.import_module(path, statement), ())
                if len(paths) == 1:
                    return self.alias_declaration(paths[0], alias.name, seen | {key})
        return None

    def alias_context(self, path, scope, context):
        """Supplement only aliases referenced in retained value dependencies."""
        path = str(Path(path).resolve())
        pending = [(path, name, scope) for name in sorted(data_names(context))]
        seen, values, diagnostics = set(), [], []
        while pending:
            source_path, name, local_scope = pending.pop()
            if (source_path, name) in seen:
                continue
            seen.add((source_path, name))
            if isinstance(local_scope, FUNCTIONS) and self.bindings(local_scope, name):
                continue
            record = self.alias_declaration(source_path, name)
            if record is None:
                continue
            origin, alias_name, declaration, value = record
            values.append(ast.unparse(declaration))
            binding = self.module_bindings(source_path, name)
            if len(binding or ()) == 1 and isinstance(binding[0], tuple):
                statement, _ = binding[0]
                values.append(ast.unparse(statement))
                diagnostics.append(dict(component='alias', alias=name, source_file=source_path,
                    source_line=statement.lineno, resolution='resolved', reason='explicit_alias_import'))
            diagnostics.append(dict(component='alias', alias=alias_name, source_file=origin,
                source_line=declaration.lineno, resolution='resolved', reason='retained_value_dependency'))
            pending.extend((origin, dependency, None) for dependency in sorted(data_names(value)))
        return list(dict.fromkeys(values)), diagnostics

    def star_exports(self, path, name, seen):
        """Prove presence/absence from project ASTs; None means unknown.

        No project module is imported or executed. Dynamic __all__, cycles and
        unavailable modules fail closed rather than guessing exported names.
        """
        export_key = ('exports', path, name)
        if export_key in seen:
            return None
        seen = seen | {export_key}
        tree = self.trees[path]
        if any(not (isinstance(b, tuple) and b[1].name == '*')
               for b in self.bindings(tree, '__getattr__')):
            return None
        # A star can itself import __all__/__getattr__ when explicitly exported.
        # Such indirect namespace policies are deliberately left unresolved.
        for statement in self.module_bodies[path]:
            if isinstance(statement, ast.ImportFrom) and any(a.name == '*' for a in statement.names):
                paths = self.by_module.get(self.import_module(path, statement), ())
                if len(paths) != 1:
                    return None
                if any(self.star_exports(paths[0], special, seen) is not False
                       for special in ('__all__', '__getattr__')):
                    return None
        all_bindings = [b for b in self.bindings(tree, '__all__')
                        if not (isinstance(b, tuple) and b[1].name == '*')]
        if all_bindings:
            declaration = next((s for s in self.module_bodies[path] if isinstance(s, (ast.Assign, ast.AnnAssign))
                and isinstance(s.value, (ast.List, ast.Tuple))
                and any(n is all_bindings[0] for n in ast.walk(s))), None)
            if len(all_bindings) != 1 or declaration is None:
                return None
            # A literal is insufficient if it is later mutated or passed away.
            if any(isinstance(n, ast.Name) and n.id == '__all__' and isinstance(n.ctx, ast.Load)
                   for s in self.module_bodies[path] for n in ast.walk(s)):
                return None
            items = declaration.value.elts
            if not all(isinstance(n, ast.Constant) and isinstance(n.value, str) for n in items):
                return None
            if name not in [n.value for n in items]:
                return False
        elif name.startswith('_'):
            return False
        if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id in {'exec', 'eval', 'setattr', 'delattr', 'globals', 'locals', 'vars'}
               for s in self.module_bodies[path] if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
               for n in ast.walk(s)):
            return None
        bindings = self.module_bindings(path, name, seen)
        if bindings is None:
            return None
        return bool(bindings) if not all_bindings else (True if bindings else None)

    def module_bindings(self, path, name, seen=frozenset()):
        """Filter wildcard bindings using proven exports, preserving ambiguity."""
        key = (path, name)
        if key in seen:
            return None
        if key in self.module_binding_cache:
            return self.module_binding_cache[key]
        tree = self.trees[path]
        result = []
        for binding in self.bindings(tree, name):
            if isinstance(binding, tuple) and binding[1].name == '*':
                statement, _ = binding
                paths = self.by_module.get(self.import_module(path, statement), ())
                exported = self.star_exports(paths[0], name, seen | {key}) if len(paths) == 1 else None
                if exported is not False:
                    result.append((statement, ast.alias(name=name)) if exported else binding)
            else:
                # An unconditional explicit binding overrides preceding stars.
                # Keep explicit rebindings ambiguous as in the existing policy.
                statement = binding[0] if isinstance(binding, tuple) else binding
                direct = statement in self.module_bodies[path] or any(binding is n for s in self.module_bodies[path]
                    if isinstance(s, (ast.Assign, ast.AnnAssign)) for n in ast.walk(s))
                if direct:
                    result = [b for b in result if not (isinstance(b, tuple)
                        and isinstance(b[0], ast.ImportFrom) and any(a.name == '*' for a in b[0].names))]
                result.append(binding)
        # Cache only outer queries: a cycle's answer can depend on its path.
        if not seen:
            self.module_binding_cache[key] = result
        return result

    @staticmethod
    def _bindings(tree, name):
        """All bindings in this lexical scope; never descend into another scope."""
        found = []
        class Bindings(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                if node.name == name:
                    found.append(node)
            visit_AsyncFunctionDef = visit_FunctionDef
            def visit_ClassDef(self, node):
                if node.name == name:
                    found.append(node)
            def visit_Lambda(self, node):
                return
            def visit_Name(self, node):
                if node.id == name and isinstance(node.ctx, (ast.Store, ast.Del)):
                    found.append(node)
            def visit_Import(self, node):
                for alias in node.names:
                    if (alias.asname or alias.name.split('.')[0]) == name:
                        found.append((node, alias))
            def visit_ImportFrom(self, node):
                for alias in node.names:
                    if alias.name == '*' or (alias.asname or alias.name) == name:
                        found.append((node, alias))
            def visit_ExceptHandler(self, node):
                if node.name == name:
                    found.append(node)
                self.generic_visit(node)
            def visit_MatchAs(self, node):
                if node.name == name:
                    found.append(node)
                self.generic_visit(node)
        visitor = Bindings()
        for statement in (static_body(tree.body) if isinstance(tree, ast.Module) else tree.body):
            visitor.visit(statement)
        if isinstance(tree, FUNCTIONS):
            found.extend(p for p in ast.walk(tree.args) if isinstance(p, ast.arg) and p.arg == name)
            # Any nonlocal/global declaration makes lexical resolution opaque.
            found.extend(n for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal)) and name in n.names)
        return found

    def resolve(self, call, caller_file, caller_function=None):
        """Fail closed: short-name matches are search candidates, never callees.

        Prove only module-level plain functions and project imports with known
        bindings, including wildcard imports whose exports can be established.
        Dynamic receivers, nested scopes and methods remain unresolved rather
        than injecting speculative bodies. No annotation participates here.
        """
        path = str(Path(caller_file).resolve())
        tree = self.trees.get(path)
        if tree is None:
            return None, 'source_unavailable'
        if caller_function is None:
            return None, 'call_scope_unavailable'
        if any(call is n for s in caller_function.body
               for nested in ast.walk(s) if isinstance(nested, (*FUNCTIONS, ast.Lambda, ast.ClassDef))
               for n in ast.walk(nested)):
            return None, 'nested_callable_scope'
        target = call.func
        chain = []
        while isinstance(target, ast.Attribute):
            chain.insert(0, target.attr)
            target = target.value
        if not isinstance(target, ast.Name):
            return None, 'dynamic_receiver'
        root = target.id
        if isinstance(caller_function, FUNCTIONS):
            # Nested functions can capture bindings not visible in this scope.
            records = self.scope_records.get((path, caller_function.lineno, caller_function.name), ())
            if len(records) != 1 or (path, caller_function.lineno, caller_function.name) in self.nested_scopes:
                return None, 'nested_scope'
            if self.bindings(records[0][2], root):
                return None, 'shadowed_name_or_receiver'
            if any(isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del)) for n in lexical_nodes(caller_function)):
                return None, 'possible_attribute_rebinding'
            if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {'exec', 'eval', 'setattr', 'delattr', 'globals', 'locals', 'vars'} for n in lexical_nodes(caller_function)):
                return None, 'dynamic_scope_effect'
        bindings = self.module_bindings(path, root)
        if len(bindings) != 1:
            return None, 'ambiguous_or_missing_binding'
        binding = bindings[0]
        traversed_modules = []
        # Module execution cannot use a definition/import that occurs later.
        if isinstance(caller_function, ast.Module):
            statement = binding[0] if isinstance(binding, tuple) else binding
            if getattr(statement, 'lineno', 0) >= call.lineno:
                return None, 'binding_after_module_call'
        if isinstance(binding, FUNCTIONS) and not chain:
            if binding not in self.module_bodies[path]:
                return None, 'conditional_definition'
            qualified = '.'.join(filter(None, (self.modules[path], root)))
            matches = self.by_identity.get((path, qualified), ())
        elif isinstance(binding, tuple):
            statement, alias = binding
            if statement not in self.module_bodies[path]:
                return None, 'conditional_import'
            if isinstance(statement, ast.ImportFrom):
                if alias.name == '*':
                    return None, 'star_import'
                module = self.import_module(path, statement)
                if module is None:
                    return None, 'invalid_relative_import'
                qualified = '.'.join(filter(None, (module, alias.name, *chain)))
            else:
                qualified = '.'.join([alias.name, *chain]) if alias.asname else '.'.join([root, *chain])
            matches, reason, traversed_modules = self.imported_function(qualified)
            if reason:
                return None, reason
        else:
            return None, 'unresolved_receiver'
        if len(matches) != 1:
            return None, 'ambiguous_or_missing_definition'
        # Module attribute assignments can replace even a lexically known name.
        for module_tree in (tree, self.trees[matches[0][0]], *(self.trees[p] for p in traversed_modules)):
            for statement in static_body(module_tree.body):
                if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if any(isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del)) for n in ast.walk(statement)):
                        return None, 'possible_attribute_rebinding'
                    if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {'exec', 'eval', 'setattr', 'delattr', 'globals', 'locals', 'vars'} for n in ast.walk(statement)):
                        return None, 'dynamic_module_effect'
        return matches[0], ''

    def lookup(self, call, caller_file, caller_function):
        record, _ = self.resolve(call, caller_file, caller_function)
        return ([record] if record else []), record is not None

    def callers(self, qualified):
        """Revalidate caller sites instead of trusting the legacy name index."""
        if self.callers_cache is None:
            self.callers_cache = {}
            for path, tree in self.trees.items():
                catalog = self
                class Calls(ast.NodeVisitor):
                    caller = tree
                    def visit_FunctionDef(self, node):
                        previous = self.caller
                        self.caller = node
                        for statement in node.body:
                            self.visit(statement)
                        self.caller = previous
                    visit_AsyncFunctionDef = visit_FunctionDef
                    def visit_If(self, node):
                        if isinstance(node.test, ast.Constant) and type(node.test.value) is bool:
                            for statement in (node.body if node.test.value else node.orelse):
                                self.visit(statement)
                        else:
                            self.generic_visit(node)
                    def visit_ClassDef(self, node):
                        for statement in node.body:
                            if isinstance(statement, FUNCTIONS):
                                self.visit(statement)
                    def visit_Lambda(self, node):
                        return
                    def visit_Call(self, node):
                        record, reason = catalog.resolve(node, path, self.caller)
                        if record is not None and self.caller is not None:
                            catalog.callers_cache.setdefault(record[1], []).append((path, self.caller, node))
                        elif record is None:
                            leaf = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
                            if leaf:
                                catalog.caller_rejections.setdefault(leaf, []).append(dict(component='caller',
                                    mode='unresolved', reason=reason, call=ast.unparse(node.func),
                                    source_file=path, source_line=node.lineno))
                        self.generic_visit(node)
                Calls().visit(tree)
        return self.callers_cache.get(qualified, ())


def reduce_class(definition, query):
    """Select whole methods and dependency attributes; never trim method bodies."""
    try:
        tree = ast.parse(definition)
        node = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    except (SyntaxError, ValueError, StopIteration):
        return definition, {'mode': 'full_fallback', 'reason': 'parse_error'}
    wanted = set((query or {}).get('methods', ())) | set((query or {}).get('attributes', ()))
    if not wanted:
        return definition, {'mode': 'full_fallback', 'reason': 'no_relevant_members'}
    declared = {}
    for i, statement in enumerate(node.body):
        values = set()
        if isinstance(statement, FUNCTIONS):
            values.add(statement.name)
            for child in ast.walk(statement):
                if isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Store) and isinstance(child.value, ast.Name) and child.value.id in {'self', 'cls'}:
                    values.add(child.attr)
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            values.update(n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name))
        elif not (isinstance(statement, ast.Pass) or isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str)):
            return definition, {'mode': 'full_fallback', 'reason': 'dynamic_class_body'}
        declared[i] = values
    all_declared = set().union(*declared.values()) if declared else set()
    for statement in node.body:
        if isinstance(statement, FUNCTIONS):
            for decorator in statement.decorator_list:
                known = isinstance(decorator, ast.Name) and decorator.id in {'property', 'staticmethod', 'classmethod'}
                known |= isinstance(decorator, ast.Attribute) and isinstance(decorator.value, ast.Name) and decorator.attr in {'setter', 'deleter', 'getter'}
                if not known:
                    return definition, {'mode': 'full_fallback', 'reason': 'method_decorator'}
    if '__init__' in wanted and '__new__' in all_declared:
        wanted.add('__new__')
    if '__slots__' in all_declared:
        wanted.add('__slots__')
    if wanted - all_declared:
        return definition, {'mode': 'full_fallback', 'reason': 'inherited_or_unknown_member'}
    # Class decorators may synthesize fields/constructors; keep the whole class.
    if node.decorator_list:
        return definition, {'mode': 'full_fallback', 'reason': 'class_decorator'}
    selected = set()
    while True:
        previous = (len(selected), len(wanted))
        for i, statement in enumerate(node.body):
            if declared[i] & wanted:
                selected.add(i)
                for child in ast.walk(statement):
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id in {'getattr', 'setattr', 'delattr', 'super', 'exec', 'eval'}:
                        return definition, {'mode': 'full_fallback', 'reason': 'dynamic_member_access'}
                    if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name) and child.value.id in {'self', 'cls', node.name}:
                        wanted.add(child.attr)
                wanted.update(body_names(statement) & all_declared)
        if wanted - all_declared:
            return definition, {'mode': 'full_fallback', 'reason': 'unresolved_member_dependency'}
        if previous == (len(selected), len(wanted)):
            break
    # Dynamic descriptors and attribute interception may affect any member.
    if {'__getattr__', '__getattribute__', '__setattr__'} & all_declared:
        return definition, {'mode': 'full_fallback', 'reason': 'dynamic_member_access'}
    result = copy.deepcopy(node)
    result.body = [s for i, s in enumerate(result.body)
                   if i in selected or (i == 0 and ast.get_docstring(node, clean=False) is not None)] or [ast.Pass()]
    rendered = ast.unparse(ast.fix_missing_locations(result))
    ast.parse(rendered)
    if len(selected) < len(node.body):
        rendered += '\n    # omitted unrelated members'
    return rendered, {'mode': 'sliced', 'reason': '', 'kept_members': sorted(wanted),
                      'before': len(node.body), 'after': len(result.body)}
