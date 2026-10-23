"""Stop value-only context expansion at independently verified type contracts.

Never consult target annotations, candidate scores or gold labels. This is not
annotation prediction: aliases and the original proving expressions stay visible.
"""
from __future__ import annotations

import ast
from pathlib import Path

from typepro.analysis.ast_context_slicer import (
    FunctionCatalog, bind_arguments, data_names, effect_reason, lexical_nodes,
)
from typepro.analysis.signature_contracts import opaque

SCALARS = frozenset({'bool', 'int', 'float', 'complex', 'str', 'bytes'})
FORMS = frozenset({'list', 'dict', 'set', 'frozenset', 'tuple', 'List', 'Dict',
                   'Set', 'FrozenSet', 'Tuple', 'Optional', 'Union', 'Sequence',
                   'Mapping', 'Iterable', 'Iterator'})


class TypeDependencies:
    """A per-target proof table; unknown expressions keep all dependencies."""

    def __init__(self, catalog, path, function, clean=lambda text: text):
        self.catalog, self.path, self.function, self.clean = catalog, str(Path(path).resolve()), function, clean
        self.proofs = {}
        self.enabled = (catalog is not None and self.path in catalog.trees
                        and not function.decorator_list
                        and not any(effect_reason(s) for s in function.body)
                        and not opaque(catalog, self.path, function))
        if self.enabled:
            for node in lexical_nodes(function):
                if isinstance(node, ast.Call):
                    proof = self._prove(node)
                    if proof is not None:
                        self.proofs[ast.dump(node, include_attributes=False)] = proof

    def _builtin(self, name):
        return (not FunctionCatalog._bindings(self.function, name)
                and not self.catalog.module_bindings(self.path, name))

    def _closed(self, node, path):
        """Accept only explicit closed forms, never Any, typevars or aliases."""
        tree = self.catalog.trees.get(str(Path(path).resolve()))
        if tree is None or node is None:
            return False
        if isinstance(node, ast.Constant):
            return node.value is None or node.value is Ellipsis
        if isinstance(node, ast.Name):
            if node.id in SCALARS:
                return not FunctionCatalog._bindings(tree, node.id)
            # A nominal project class is concrete; unexpanded aliases are not.
            bindings = FunctionCatalog._bindings(tree, node.id)
            return (len(bindings) == 1 and isinstance(bindings[0], ast.ClassDef)
                    and not getattr(bindings[0], 'type_params', ())
                    and not any(isinstance(b, ast.Subscript) for b in bindings[0].bases))
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return self._closed(node.left, path) and self._closed(node.right, path)
        if isinstance(node, ast.Subscript):
            base = node.value
            if not isinstance(base, ast.Name) or base.id not in FORMS:
                return False
            if base.id in {'list', 'dict', 'set', 'frozenset', 'tuple'}:
                if FunctionCatalog._bindings(tree, base.id):
                    return False
            else:
                from typepro.analysis.type_aliases import typing_symbol
                if typing_symbol(tree, base) != base.id:
                    return False
            items = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            return bool(items) and all(self._closed(n, path) for n in items)
        return False

    def _prove(self, call):
        # Scalar constructors determine their result independently of the input
        # representation. Container constructors and type(x) deliberately do not.
        if isinstance(call.func, ast.Name) and call.func.id in SCALARS and self._builtin(call.func.id):
            if any(isinstance(n, ast.Starred) for n in call.args) or any(k.arg is None for k in call.keywords):
                return None
            return {'reason': 'verified_scalar_constructor', 'contract': call.func.id,
                    'value_independent': True}
        record, _ = self.catalog.resolve(call, self.path, self.function)
        if record is None:
            return None
        path, qualified, original, nested = record
        # Only plain sync functions. Async calls and generators return wrappers,
        # decorators and overloads can change the apparent contract.
        if nested or not isinstance(original, ast.FunctionDef) or original.decorator_list:
            return None
        fn = ast.parse(self.clean(ast.unparse(original))).body[0]
        if any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in ast.walk(fn)):
            return None
        bound, _ = bind_arguments(fn, call)
        if bound is None or not self._closed(fn.returns, path):
            return None
        return {'reason': 'verified_closed_return_contract', 'contract': ast.unparse(fn.returns),
                'value_independent': isinstance(fn.returns, ast.Name) and fn.returns.id in SCALARS,
                'callee': qualified, 'source_file': path, 'source_line': original.lineno}

    def proof(self, call):
        return self.proofs.get(ast.dump(call, include_attributes=False))

    def dependencies(self, expression):
        """Preserve the callable contract, stop only its value argument edges."""
        if isinstance(expression, ast.Call) and (self.proof(expression) or {}).get('value_independent'):
            return data_names(expression.func)
        if isinstance(expression, ast.Name):
            return {expression.id}
        if isinstance(expression, ast.Lambda):
            return data_names(expression)
        found = set()
        for field, value in ast.iter_fields(expression):
            if field in {'annotation', 'returns'}:
                continue
            for child in value if isinstance(value, list) else [value]:
                if isinstance(child, ast.AST):
                    found.update(self.dependencies(child))
        return found

    def result_calls(self, expression):
        calls = set()
        def visit(node):
            if isinstance(node, ast.Call):
                calls.add(id(node))
                if (self.proof(node) or {}).get('value_independent'):
                    return
            for child in ast.iter_child_nodes(node):
                visit(child)
        visit(expression)
        return calls

    def statement_dependencies(self, statement):
        if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.Return)) and statement.value is not None:
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target] if isinstance(statement, ast.AnnAssign) else []
            # Keep declared types and their initializers together: they may name
            # useful aliases even when their value no longer determines a type.
            if isinstance(statement, ast.AnnAssign):
                return data_names(statement)
            return self.dependencies(statement.value) | set().union(*(data_names(t) for t in targets))
        return data_names(statement)
