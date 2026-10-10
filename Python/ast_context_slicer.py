"""Conservative, non-executing AST context reduction.

Blocks are reduced recursively. This selects type evidence, not an executable
program transformation; unknown dynamic scope effects are reported explicitly.
"""
from __future__ import annotations

import ast
import copy
from dataclasses import dataclass
from pathlib import Path

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
POLICY = 'ast-context-v3-recursive-signature-first'
CANDIDATE_DEFINITION_MAX_CHARS = 16000


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

    def diagnostics(self):
        return dict(mode=self.mode, reason=self.reason, before=self.before, after=self.after)


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
        changed = previous != effect_objects
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
            ref = references[id(statement)]
            # Preserve loop exits and early function exits affecting selected
            # evidence, but never retain an unrelated block just for its header.
            transfer = isinstance(statement, (ast.Break, ast.Continue, ast.Return, ast.Raise))
            affects_control = transfer and any(id(p) in selected for p in parents[id(statement)])
            possible_mutation = any(isinstance(n, ast.Call) and any(data_names(v) & effect_objects
                for v in [*n.args, *(k.value for k in n.keywords)]) for n in ast.walk(statement))
            if ref & flow or writes[id(statement)] & live or receivers[id(statement)] & live or affects_control or possible_mutation:
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
    result.body = render(function.body) or [ast.Pass()]
    ast.fix_missing_locations(result)
    ast.parse(ast.unparse(result))
    after = sum(isinstance(n, ast.stmt) for s in result.body for n in ast.walk(s))
    return Reduction(result, 'sliced', '', before, after)


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
    def __init__(self, parsed_files):
        self.records = []
        self.trees = {}
        self.modules = {}
        self.by_module = {}
        self.callers_cache = None
        self.nested_scopes = set()
        for path, module, source, tree in parsed_files:
            path = str(Path(path).resolve())
            self.trees[path] = tree
            self.modules[path] = module
            self.by_module.setdefault(module, []).append(path)
            def visit(body, scopes=(), function_depth=0):
                for node in body:
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
        for record in self.records:
            self.by_identity.setdefault((record[0], record[1]), []).append(record)
            self.scope_records.setdefault((record[0], record[2].lineno, record[2].name), []).append(record)

    def bindings(self, tree, name):
        key = (id(tree), name)
        if key not in self.binding_cache:
            self.binding_cache[key] = self._bindings(tree, name)
        return self.binding_cache[key]

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
        for statement in tree.body:
            visitor.visit(statement)
        if isinstance(tree, FUNCTIONS):
            found.extend(p for p in ast.walk(tree.args) if isinstance(p, ast.arg) and p.arg == name)
            # Any nonlocal/global declaration makes lexical resolution opaque.
            found.extend(n for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal)) and name in n.names)
        return found

    def resolve(self, call, caller_file, caller_function=None):
        """Fail closed: short-name matches are search candidates, never callees.

        Prove only module-level plain functions and explicit project imports.
        Dynamic receivers, nested scopes and methods remain unresolved rather
        than injecting speculative bodies. No annotation participates here.
        """
        path = str(Path(caller_file).resolve())
        tree = self.trees.get(path)
        if tree is None:
            return None, 'source_unavailable'
        if caller_function is None:
            return None, 'call_scope_unavailable'
        if any(isinstance(n, (ast.Lambda, *FUNCTIONS)) for s in caller_function.body for n in ast.walk(s)):
            return None, 'nested_callable_scope'
        target = call.func
        chain = []
        while isinstance(target, ast.Attribute):
            chain.insert(0, target.attr)
            target = target.value
        if not isinstance(target, ast.Name):
            return None, 'dynamic_receiver'
        root = target.id
        if caller_function is not None:
            # Nested functions can capture bindings not visible in this scope.
            records = self.scope_records.get((path, caller_function.lineno, caller_function.name), ())
            if len(records) != 1 or (path, caller_function.lineno, caller_function.name) in self.nested_scopes:
                return None, 'nested_scope'
            if self.bindings(records[0][2], root):
                return None, 'shadowed_name_or_receiver'
            if any(isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del)) for n in ast.walk(caller_function)):
                return None, 'possible_attribute_rebinding'
            if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {'exec', 'eval', 'setattr', 'delattr', 'globals', 'locals', 'vars'} for n in ast.walk(caller_function)):
                return None, 'dynamic_scope_effect'
        bindings = self.bindings(tree, root)
        if len(bindings) != 1:
            return None, 'ambiguous_or_missing_binding'
        binding = bindings[0]
        if isinstance(binding, FUNCTIONS) and not chain:
            if binding not in tree.body:
                return None, 'conditional_definition'
            qualified = '.'.join(filter(None, (self.modules[path], root)))
            matches = self.by_identity.get((path, qualified), ())
        elif isinstance(binding, tuple):
            statement, alias = binding
            if statement not in tree.body:
                return None, 'conditional_import'
            if isinstance(statement, ast.ImportFrom):
                if alias.name == '*':
                    return None, 'star_import'
                module = statement.module or ''
                if statement.level:
                    package = self.modules[path].split('.')
                    if Path(path).name != '__init__.py':
                        package = package[:-1]
                    if statement.level > len(package):
                        return None, 'invalid_relative_import'
                    module = '.'.join(package[:len(package) - statement.level + 1] + ([module] if module else []))
                qualified = '.'.join(filter(None, (module, alias.name, *chain)))
            else:
                qualified = '.'.join([alias.name, *chain]) if alias.asname else '.'.join([root, *chain])
            # Only standalone functions directly declared by that module.
            module = qualified.rsplit('.', 1)[0] if '.' in qualified else ''
            paths = self.by_module.get(module, ())
            matches = [r for p in paths for r in self.by_identity.get((p, qualified), ()) if not r[3]]
            if len(paths) != 1:
                return None, 'ambiguous_import_module'
            if matches and (matches[0][2] not in self.trees[matches[0][0]].body or self.bindings(self.trees[matches[0][0]], matches[0][2].name) != [matches[0][2]]):
                return None, 'rebound_imported_function'
        else:
            return None, 'unresolved_receiver'
        if len(matches) != 1:
            return None, 'ambiguous_or_missing_definition'
        # Module attribute assignments can replace even a lexically known name.
        for module_tree in (tree, self.trees[matches[0][0]]):
            for statement in module_tree.body:
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
                    caller = None
                    def visit_FunctionDef(self, node):
                        previous = self.caller
                        self.caller = node
                        for statement in node.body:
                            self.visit(statement)
                        self.caller = previous
                    visit_AsyncFunctionDef = visit_FunctionDef
                    def visit_Lambda(self, node):
                        return
                    def visit_Call(self, node):
                        record, _ = catalog.resolve(node, path, self.caller)
                        if record is not None and self.caller is not None:
                            catalog.callers_cache.setdefault(record[1], []).append((path, self.caller, node))
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
    result.body = [s for i, s in enumerate(result.body) if i in selected] or [ast.Pass()]
    rendered = ast.unparse(ast.fix_missing_locations(result))
    ast.parse(rendered)
    if len(selected) < len(node.body):
        rendered += '\n    # omitted unrelated members'
    return rendered, {'mode': 'sliced', 'reason': '', 'kept_members': sorted(wanted),
                      'before': len(node.body), 'after': len(result.body)}
