"""Conservative, non-executing AST context reduction.

Compound statements stay whole. Unknown binding/effects retain whole functions;
this is evidence selection, not an executable program transformation.
"""
from __future__ import annotations

import ast
import copy
from dataclasses import dataclass
from pathlib import Path

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
POLICY = 'ast-context-v2-resolved-callees-bounded-candidates'
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


def reduce_function(function, parameters=(), returns=False):
    """Keep a conservative connected dependency component at statement level.

    All possible writes are retained (including redefinitions). Calls touching
    selected objects retain side effects. Blocks and control transfers remain
    whole, including early returns that could affect an implicit None path.
    """
    result = ast.parse(ast.unparse(function)).body[0]
    before = len(function.body)
    for statement in function.body:
        reason = effect_reason(statement)
        if reason:
            return Reduction(result, 'full_fallback', reason, before, before)
    live = set(parameters)
    selected = set()
    # Returns/raises/control blocks must survive even when not mentioning a
    # parameter: they govern whether its uses are reachable.
    control = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith)
    if hasattr(ast, 'Match'):
        control += (ast.Match,)
    if hasattr(ast, 'TryStar'):
        control += (ast.TryStar,)
    refs = [body_names(s) for s in function.body]
    for i, statement in enumerate(function.body):
        has_exit = any(isinstance(n, (ast.Return, ast.Raise, ast.Yield, ast.YieldFrom))
                       for n in ast.walk(statement))
        if isinstance(statement, control) or has_exit:
            selected.add(i)
            live.update(refs[i])
    if not live and not selected:
        return Reduction(result, 'full_fallback', 'no_dependency_seed', before, before)
    while True:
        previous = (len(selected), len(live))
        for i, ref in enumerate(refs):
            if ref & live:
                selected.add(i)
                live.update(ref)
        if previous == (len(selected), len(live)):
            break
    # Only discard inert local literal declarations in v1. An unrelated call,
    # attribute access/operator, delete or external store may affect state or
    # control flow. Unknown effects require whole-function fallback.
    for i, statement in enumerate(function.body):
        if i not in selected:
            value = getattr(statement, 'value', None)
            targets = statement.targets if isinstance(statement, ast.Assign) else (
                [statement.target] if isinstance(statement, ast.AnnAssign) else [])
            inert = bool(targets) and all(isinstance(t, ast.Name) for t in targets)
            def literal(n):
                return isinstance(n, ast.Constant) or isinstance(n, (ast.Tuple, ast.List, ast.Set)) and all(literal(e) for e in n.elts) or isinstance(n, ast.Dict) and all(k is not None and literal(k) and literal(v) for k, v in zip(n.keys, n.values))
            inert = inert and (value is None or literal(value))
            if not inert:
                return Reduction(result, 'full_fallback', 'unresolved_side_effect', before, before)
    result.body = [s for i, s in enumerate(result.body) if i in selected] or [ast.Pass()]
    ast.fix_missing_locations(result)
    ast.parse(ast.unparse(result))
    return Reduction(result, 'sliced', '', before, len(result.body))


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
