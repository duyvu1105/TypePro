"""High-recall type signals that never inspect the target annotation.

The analyzer combines syntax visible in a masked slice with project-wide
imports, stubs, constructors, call returns, call-site arguments, fixtures and
common factory/framework idioms.  Project parameter annotations are
deliberately not indexed: one of them may be the label currently being masked.
"""
from __future__ import annotations

import ast
import os
from collections import defaultdict
from pathlib import Path
from typing import Iterable


SKIP_DIRECTORIES = {
    ".git", ".hg", ".mypy_cache", ".pytest_cache", ".tox", ".venv",
    "__pycache__", "build", "dist", "node_modules", "venv",
}
TYPE_WRAPPERS = {
    "Annotated", "AsyncGenerator", "Awaitable", "Callable", "ClassVar",
    "Collection", "Coroutine", "Dict", "Final", "Generator", "Generic",
    "Iterable", "Iterator", "List", "Literal", "Mapping", "MutableMapping",
    "Optional", "Protocol", "Sequence", "Set", "Tuple", "Type", "Union",
}
NON_TYPE_CALLS = {
    "all", "any", "enumerate", "filter", "len", "map", "max", "min",
    "next", "open", "print", "range", "reversed", "sorted", "sum", "zip",
}
FACTORY_METHODS = {
    "build", "construct", "create", "factory", "from_dict", "from_json",
    "from_orm", "load", "make", "model_validate", "new", "parse_obj",
}


def _name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _leaf(value: str) -> str:
    return value.strip(" '\"").rsplit(".", 1)[-1]


def _is_type_name(value: str) -> bool:
    leaf = _leaf(value)
    return bool(leaf and leaf.isidentifier() and (
        leaf[:1].isupper() or leaf in {"datetime", "date", "time", "socket"}
    ))


def _definition(name: str, source: str, kind: str, module: str = "") -> str:
    lines = [f"class {name}:"]
    if module:
        lines.append(f"    # module: {module}")
    lines.extend((f"    # source: {source}", f"    # kind: {kind}"))
    return "\n".join(lines)


def annotation_names(node: ast.AST | None) -> set[str]:
    """Return concrete names nested in a type expression."""
    if node is None:
        return set()
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            return annotation_names(ast.parse(node.value, mode="eval").body)
        except (SyntaxError, ValueError):
            return {_leaf(node.value)} if _is_type_name(node.value) else set()
    names = set()
    for child in ast.walk(node):
        value = ""
        if isinstance(child, ast.Name):
            value = child.id
        elif isinstance(child, ast.Attribute):
            value = child.attr
        if value and value not in TYPE_WRAPPERS and value not in {"None", "Any"}:
            if _is_type_name(value):
                names.add(_leaf(value))
    return names


def visible_type_signals(source: str) -> list[str]:
    """Collect type uses from a masked slice, including tolerant fallbacks."""
    parse_source = source.replace("<mask>", "TYPEPRO_MASK")
    try:
        tree = ast.parse(parse_source)
    except (SyntaxError, ValueError):
        tree = None
    found: dict[str, str] = {}

    def add(name: str, kind: str) -> None:
        name = _leaf(name)
        if name and name != "TYPEPRO_MASK" and _is_type_name(name):
            found.setdefault(name, _definition(name, "slice", kind))

    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name != "*":
                        add(alias.asname or alias.name, "import_symbol")
            elif isinstance(node, ast.ClassDef):
                add(node.name, "visible_class")
                for base in node.bases:
                    for name in annotation_names(base):
                        add(name, "base_class")
            elif isinstance(node, ast.AnnAssign):
                for name in annotation_names(node.annotation):
                    add(name, "annotation")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for argument in [
                    *getattr(node.args, "posonlyargs", []), *node.args.args,
                    *node.args.kwonlyargs,
                ]:
                    for name in annotation_names(argument.annotation):
                        add(name, "annotation")
                for name in annotation_names(node.returns):
                    add(name, "return_annotation")
            elif isinstance(node, ast.Call):
                call_name = _name(node.func)
                leaf = _leaf(call_name)
                if leaf in {"isinstance", "issubclass"} and len(node.args) >= 2:
                    for name in annotation_names(node.args[1]):
                        add(name, leaf)
                elif leaf == "cast" and node.args:
                    for name in annotation_names(node.args[0]):
                        add(name, "cast")
                elif _is_type_name(leaf) and leaf not in NON_TYPE_CALLS:
                    add(leaf, "constructor")
                if leaf in {"MagicMock", "Mock"}:
                    for keyword in node.keywords:
                        if keyword.arg in {"spec", "spec_set"}:
                            add(_name(keyword.value), "mock_spec")
            elif isinstance(node, ast.Attribute) and _is_type_name(node.attr):
                add(node.attr, "qualified_attribute")
    else:
        # Interprocedural slices can concatenate snippets that are valid alone
        # but invalid as one module.  Preserve obvious type-shaped tokens.
        import re
        for match in re.finditer(
            r"(?m)^\s*from\s+[\w.]+\s+import\s+(?:\([^)]*\)|[^\n]*)",
            source,
        ):
            for name in re.findall(r"\b[A-Z][A-Za-z0-9_]*\b", match.group(0)):
                add(name, "import_symbol")
        for name in re.findall(
            r"(?:\.|\bclass\s+|\bcast\s*\(|\bisinstance\s*\([^,]+,)\s*"
            r"([A-Z][A-Za-z0-9_]*)",
            source,
        ):
            add(name, "tolerant_syntax")
    return list(found.values())


class ProjectTypeAnalyzer:
    """A bounded project-wide semantic index used by every annotation."""

    def __init__(
        self,
        project_root: str | os.PathLike[str] | None,
        parsed_files=None,
    ):
        self.root = Path(project_root).resolve() if project_root else None
        self.definitions: dict[str, list[str]] = defaultdict(list)
        self.module_symbols: dict[str, set[str]] = defaultdict(set)
        self.file_imports: dict[str, set[str]] = defaultdict(set)
        self.variable_types: dict[str, set[str]] = defaultdict(set)
        self.parameter_types: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.function_returns: dict[str, set[str]] = defaultdict(set)
        self._trees: list[tuple[Path, str, ast.Module]] = []
        self._functions: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = defaultdict(list)
        self._star_imports: list[tuple[str, str, str]] = []
        if self.root and self.root.is_dir():
            self._build(parsed_files)

    def _files(self) -> Iterable[Path]:
        assert self.root is not None
        for directory, names, files in os.walk(self.root):
            names[:] = [name for name in names if name not in SKIP_DIRECTORIES]
            for name in files:
                if name.endswith((".py", ".pyi")):
                    yield Path(directory) / name

    def _module(self, path: Path) -> str:
        assert self.root is not None
        relative = path.relative_to(self.root).with_suffix("")
        parts = list(relative.parts)
        if parts and parts[0] == "src":
            parts.pop(0)
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    def _add_definition(self, name: str, source: str, kind: str, module: str) -> None:
        value = _definition(name, source, kind, module)
        if value not in self.definitions[name]:
            self.definitions[name].append(value)
        self.module_symbols[module].add(name)

    def _build(self, parsed_files=None) -> None:
        if parsed_files is None:
            sources = []
            for path in self._files():
                try:
                    source = path.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(source, filename=str(path))
                except (OSError, SyntaxError, ValueError):
                    continue
                sources.append((path, source, tree))
        else:
            sources = [
                (Path(path), source, tree)
                for path, _module, source, tree in parsed_files
            ]
        for path, source, tree in sources:
            module = self._module(path)
            self._trees.append((path.resolve(), module, tree))
            source_kind = "project_stub" if path.suffix == ".pyi" else "project"
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    self._add_definition(node.name, source_kind, "class", module)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self._functions[node.name].append(node)
                    # Return annotations are API contracts. Parameter
                    # annotations are intentionally ignored to avoid labels.
                    self.function_returns[node.name].update(annotation_names(node.returns))
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    if _leaf(_name(node.annotation)) == "TypeAlias":
                        self._add_definition(node.target.id, source_kind, "alias", module)

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    target_module = self._absolute_from_module(module, path, node)
                    for alias in node.names:
                        if alias.name == "*":
                            self._star_imports.append(
                                (str(path.resolve()), module, target_module)
                            )
                            continue
                        local = alias.asname or alias.name
                        self.file_imports[str(path.resolve())].add(local)
                        if alias.asname and _is_type_name(alias.name):
                            self.file_imports[str(path.resolve())].add(alias.name)
                        if _is_type_name(local):
                            self._add_definition(
                                local, source_kind, "reexported_import", target_module
                            )
                            self.module_symbols[module].add(local)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        local = alias.asname or alias.name.split(".", 1)[0]
                        self.file_imports[str(path.resolve())].add(local)

        # Resolve star imports and re-export chains after all modules have
        # contributed their concrete class/alias symbols.
        for _ in range(5):
            changed = False
            for file_name, current_module, target_module in self._star_imports:
                exported = {
                    name for name in self.module_symbols.get(target_module, ())
                    if not name.startswith("_")
                }
                before = len(self.file_imports[file_name])
                self.file_imports[file_name].update(exported)
                self.module_symbols[current_module].update(exported)
                changed |= len(self.file_imports[file_name]) != before
            if not changed:
                break

        # Infer returns and assignments to a small fixed point so wrappers and
        # short factory chains resolve without an expensive whole-program solver.
        for _ in range(5):
            changed = False
            for path, _, tree in self._trees:
                for function in (
                    node for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                ):
                    env: dict[str, set[str]] = defaultdict(set)
                    before = len(self.function_returns[function.name])
                    for statement in function.body:
                        self._process_statement(statement, env, function.name)
                    changed |= len(self.function_returns[function.name]) != before
                module_env: dict[str, set[str]] = defaultdict(set)
                for statement in tree.body:
                    if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        self._process_statement(statement, module_env, "")
            if not changed:
                break
        # Alternate call-site and callee-body propagation. This resolves
        # unannotated wrappers such as ``return identity(factory())`` while
        # remaining bounded on recursive call graphs.
        for _ in range(5):
            before = (
                sum(map(len, self.function_returns.values())),
                sum(map(len, self.parameter_types.values())),
                sum(map(len, self.variable_types.values())),
            )
            self._propagate_call_arguments()
            for _, _, tree in self._trees:
                for function in (
                    node for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                ):
                    env: dict[str, set[str]] = defaultdict(set)
                    for parameter in [
                        *getattr(function.args, "posonlyargs", []),
                        *function.args.args, *function.args.kwonlyargs,
                    ]:
                        env[parameter.arg].update(
                            self.parameter_types.get((function.name, parameter.arg), ())
                        )
                    for statement in function.body:
                        self._process_statement(statement, env, function.name)
            after = (
                sum(map(len, self.function_returns.values())),
                sum(map(len, self.parameter_types.values())),
                sum(map(len, self.variable_types.values())),
            )
            if after == before:
                break
        self._propagate_call_arguments()

    @staticmethod
    def _absolute_from_module(
        current_module: str, path: Path, node: ast.ImportFrom
    ) -> str:
        if node.level == 0:
            return node.module or ""
        package = current_module if path.stem == "__init__" else current_module.rpartition(".")[0]
        parts = package.split(".") if package else []
        keep = max(0, len(parts) - (node.level - 1))
        base = parts[:keep]
        if node.module:
            base.extend(node.module.split("."))
        return ".".join(base)

    def _expr_types(self, expression: ast.AST | None, env: dict[str, set[str]]) -> set[str]:
        if expression is None:
            return set()
        if isinstance(expression, ast.Name):
            return set(env.get(expression.id, ()))
        if isinstance(expression, ast.Await):
            return self._expr_types(expression.value, env)
        if isinstance(expression, (ast.IfExp, ast.BoolOp)):
            values = expression.values if isinstance(expression, ast.BoolOp) else [expression.body, expression.orelse]
            return set().union(*(self._expr_types(value, env) for value in values))
        if isinstance(expression, (ast.List, ast.Tuple, ast.Set)):
            return set().union(*(self._expr_types(value, env) for value in expression.elts))
        if not isinstance(expression, ast.Call):
            return set()
        call_name = _name(expression.func)
        leaf = _leaf(call_name)
        results = set(self.function_returns.get(leaf, ()))
        if _is_type_name(leaf) and leaf not in NON_TYPE_CALLS:
            results.add(leaf)
        # Django/SQLAlchemy-like managers: User.objects.get(), query(User).first().
        if ".objects." in call_name:
            owner = call_name.split(".objects.", 1)[0].rsplit(".", 1)[-1]
            if _is_type_name(owner):
                results.add(owner)
        for node in ast.walk(expression.func):
            if isinstance(node, ast.Call) and _leaf(_name(node.func)) == "query" and node.args:
                candidate = _leaf(_name(node.args[0]))
                if _is_type_name(candidate):
                    results.add(candidate)
        if isinstance(expression.func, ast.Attribute) and leaf in FACTORY_METHODS:
            owner = _leaf(_name(expression.func.value))
            if _is_type_name(owner):
                results.add(owner.removesuffix("Factory") or owner)
        if leaf in {"MagicMock", "Mock"}:
            results.add(leaf)
            for keyword in expression.keywords:
                if keyword.arg in {"spec", "spec_set"}:
                    candidate = _leaf(_name(keyword.value))
                    if _is_type_name(candidate):
                        results.add(candidate)
        return results

    def _process_statement(
        self, statement: ast.stmt, env: dict[str, set[str]], function_name: str
    ) -> None:
        targets: list[str] = []
        value: ast.AST | None = None
        if isinstance(statement, ast.Assign):
            value = statement.value
            targets = [target.id for target in statement.targets if isinstance(target, ast.Name)]
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            value = statement.value
            targets = [statement.target.id]
        if targets:
            inferred = self._expr_types(value, env)
            for target in targets:
                env[target].update(inferred)
                self.variable_types[target].update(inferred)
        if isinstance(statement, ast.Return):
            self.function_returns[function_name].update(self._expr_types(statement.value, env))
        for child in ast.iter_child_nodes(statement):
            if isinstance(child, ast.stmt):
                self._process_statement(child, env, function_name)

    def _propagate_call_arguments(self) -> None:
        for _, _, tree in self._trees:
            for caller in (
                node for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ):
                env: dict[str, set[str]] = defaultdict(set)
                for parameter in [
                    *getattr(caller.args, "posonlyargs", []),
                    *caller.args.args, *caller.args.kwonlyargs,
                ]:
                    env[parameter.arg].update(
                        self.parameter_types.get((caller.name, parameter.arg), ())
                    )
                for statement in caller.body:
                    self._process_statement(statement, env, caller.name)
                for call in (node for node in ast.walk(caller) if isinstance(node, ast.Call)):
                    callee = _leaf(_name(call.func))
                    for target in self._functions.get(callee, ()):
                        parameters = [*getattr(target.args, "posonlyargs", []), *target.args.args]
                        for parameter, argument in zip(parameters, call.args):
                            self.parameter_types[(callee, parameter.arg)].update(
                                self._expr_types(argument, env)
                            )
                        by_name = {argument.arg: argument for argument in parameters}
                        for keyword in call.keywords:
                            if keyword.arg in by_name:
                                self.parameter_types[(callee, keyword.arg)].update(
                                    self._expr_types(keyword.value, env)
                                )
            module_env: dict[str, set[str]] = defaultdict(set)
            module_statements = [
                statement for statement in tree.body
                if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ]
            for statement in module_statements:
                self._process_statement(statement, module_env, "")
            for statement in module_statements:
                for call in (node for node in ast.walk(statement) if isinstance(node, ast.Call)):
                    callee = _leaf(_name(call.func))
                    for target in self._functions.get(callee, ()):
                        parameters = [*getattr(target.args, "posonlyargs", []), *target.args.args]
                        for parameter, argument in zip(parameters, call.args):
                            self.parameter_types[(callee, parameter.arg)].update(
                                self._expr_types(argument, module_env)
                            )
                        parameter_names = {parameter.arg for parameter in parameters}
                        for keyword in call.keywords:
                            if keyword.arg in parameter_names:
                                self.parameter_types[(callee, keyword.arg)].update(
                                    self._expr_types(keyword.value, module_env)
                                )
            # Pytest injects fixture functions by matching parameter names.
            fixtures = {}
            for name, functions in self._functions.items():
                if any(
                    _leaf(_name(decorator.func if isinstance(decorator, ast.Call) else decorator)) == "fixture"
                    for function in functions for decorator in function.decorator_list
                ):
                    fixtures[name] = self.function_returns.get(name, set())
            for name, functions in self._functions.items():
                for function in functions:
                    for parameter in [*function.args.args, *function.args.kwonlyargs]:
                        self.parameter_types[(name, parameter.arg)].update(
                            fixtures.get(parameter.arg, ())
                        )

    def recommendations(
        self, file_path: str, target_name: str, function_name: str = "",
        limit: int = 120,
    ) -> list[str]:
        ordered_names = []
        if function_name:
            ordered_names.extend(sorted(self.parameter_types.get((function_name, target_name), ())))
        ordered_names.extend(sorted(self.variable_types.get(target_name, ())))
        ordered_names.extend(sorted(self.file_imports.get(str(Path(file_path).resolve()), ())))
        definitions = []
        for name in dict.fromkeys(ordered_names):
            matched = self.definitions.get(name)
            if matched:
                definitions.extend(matched)
            elif _is_type_name(name):
                definitions.append(_definition(name, "project_analysis", "inferred"))
            if len(definitions) >= limit:
                break
        return list(dict.fromkeys(definitions))[:limit]
