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
POLICY = 'ast-context-v1'


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
        for path, module, source, tree in parsed_files:
            path = str(Path(path).resolve())
            self.trees[path] = tree
            def visit(body, scopes=()):
                for node in body:
                    if isinstance(node, FUNCTIONS):
                        qualified = '.'.join(filter(None, (module, *scopes, node.name)))
                        self.records.append((path, qualified, node, bool(scopes)))
                        visit(node.body, (*scopes, node.name))
                    elif isinstance(node, ast.ClassDef):
                        visit(node.body, (*scopes, node.name))
            visit(tree.body)

    def lookup(self, call, caller_file, caller_function):
        """Only unshadowed same-module plain functions are certain in v1.

        Imported, nested and descriptor calls retain full candidate bodies.
        Name-only matches must never be treated as a proven callee.
        """
        spelling = ast.unparse(call.func)
        leaf = spelling.rsplit('.', 1)[-1]
        matches = [r for r in self.records if r[1] == spelling]
        if not matches:
            matches = [r for r in self.records if r[2].name == leaf]
        path = str(Path(caller_file).resolve())
        local = [r for r in matches if r[0] == path and not r[3]]
        certain = isinstance(call.func, ast.Name) and len(local) == 1
        if certain:
            tree = self.trees[path]
            # Exclude import/assignment/rebinding at module scope, and any
            # parameter or assignment in the caller that shadows the name.
            for statement in tree.body:
                if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if leaf in names(statement) or any(
                        isinstance(n, ast.alias) and (n.asname or n.name.split('.')[0]) == leaf
                        for n in ast.walk(statement)
                    ):
                        certain = False
            if caller_function is not None:
                if any(p.arg == leaf for p in ast.walk(caller_function.args) if isinstance(p, ast.arg)):
                    certain = False
                for statement in caller_function.body:
                    if any(isinstance(n, ast.Name) and n.id == leaf and isinstance(n.ctx, (ast.Store, ast.Del))
                           for n in ast.walk(statement)):
                        certain = False
        return (local if certain else matches), certain


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
