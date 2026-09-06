"""Build project-local TypePro indexes from one shared AST scan."""
from __future__ import annotations

import ast
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from readClassDefined import extract_class_summary
from readFunctionDefined import has_type_annotations
from type_defined import ProjectClassDefine, ProjectDefined, ProjectUseData


SKIP_DIRECTORIES = {
    ".git", ".hg", ".mypy_cache", ".pytest_cache", ".tox", ".venv",
    "__pycache__", "build", "dist", "node_modules", "venv",
}
ParsedFile = tuple[Path, str, str, ast.Module]


def python_files(root: Path) -> Iterable[Path]:
    for directory, names, files in os.walk(root):
        names[:] = sorted(
            name for name in names
            if name not in SKIP_DIRECTORIES and not name.startswith(".")
        )
        for name in sorted(files):
            if name.endswith((".py", ".pyi")):
                yield Path(directory) / name


def module_name(root: Path, path: Path) -> str:
    relative = path.resolve().relative_to(root.resolve()).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[0] == "src":
        parts.pop(0)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def qualified(module: str, scopes: Iterable[str], name: str) -> str:
    return ".".join(part for part in (module, *scopes, name) if part)


def format_args(args_node: ast.arguments) -> list[str]:
    params = []
    positional = [*getattr(args_node, "posonlyargs", []), *args_node.args]
    defaults = [None] * (len(positional) - len(args_node.defaults)) + list(args_node.defaults)
    for argument, default in zip(positional, defaults):
        value = argument.arg
        if argument.annotation:
            value += f": {ast.unparse(argument.annotation)}"
        if default is not None:
            value += f" = {ast.unparse(default)}"
        params.append(value)
    if args_node.vararg:
        value = args_node.vararg.arg
        if args_node.vararg.annotation:
            value += f": {ast.unparse(args_node.vararg.annotation)}"
        params.append(f"*{value}")
    for argument, default in zip(args_node.kwonlyargs, args_node.kw_defaults):
        value = argument.arg
        if argument.annotation:
            value += f": {ast.unparse(argument.annotation)}"
        if default is not None:
            value += f" = {ast.unparse(default)}"
        params.append(value)
    if args_node.kwarg:
        value = args_node.kwarg.arg
        if args_node.kwarg.annotation:
            value += f": {ast.unparse(args_node.kwarg.annotation)}"
        params.append(f"**{value}")
    return params


def function_source(source: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    if not has_type_annotations(node):
        return ast.get_source_segment(source, node) or ast.unparse(node)
    signature = f"{node.name}({', '.join(format_args(node.args))})"
    if node.returns:
        signature += f" -> {ast.unparse(node.returns)}"
    return "function " + signature


class DefinitionVisitor(ast.NodeVisitor):
    def __init__(self, module: str, path: Path, source: str):
        self.module = module
        self.path = path
        self.source = source
        self.scopes: list[str] = []
        self.functions: list[ProjectDefined] = []
        self.class_names: dict[str, list[str]] = defaultdict(list)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        class_name = qualified(self.module, self.scopes, node.name)
        self.class_names[node.name].append(class_name)
        self.scopes.append(node.name)
        self.generic_visit(node)
        self.scopes.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        name = qualified(self.module, self.scopes, node.name)
        self.functions.append(ProjectDefined(
            node.name,
            function_source(self.source, node),
            name,
            str(self.path),
        ))
        self.scopes.append(node.name)
        self.generic_visit(node)
        self.scopes.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function


class UseVisitor(ast.NodeVisitor):
    def __init__(
        self,
        module: str,
        path: Path,
        source: str,
        functions_by_name: dict[str, list[ProjectDefined]],
        classes_by_name: dict[str, list[str]],
    ):
        self.module = module
        self.path = path
        self.source = source
        self.functions_by_name = functions_by_name
        self.classes_by_name = classes_by_name
        self.scopes: list[str] = []
        self.class_scopes: list[str] = []
        self.uses: list[ProjectUseData] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scopes.append(node.name)
        self.class_scopes.append(node.name)
        self.generic_visit(node)
        self.class_scopes.pop()
        self.scopes.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scopes.append(node.name)
        self.generic_visit(node)
        self.scopes.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def resolve(self, call: ast.Call) -> tuple[str, str] | None:
        target = call.func
        if isinstance(target, ast.Name):
            constructor_matches = [
                f"{class_name}.__init__"
                for class_name in self.classes_by_name.get(target.id, [])
                if any(
                    item.qualified_name == f"{class_name}.__init__"
                    for item in self.functions_by_name.get("__init__", [])
                )
            ]
            if len(constructor_matches) == 1:
                return "__init__", constructor_matches[0]
            candidates = self.functions_by_name.get(target.id, [])
            local = [
                item.qualified_name for item in candidates
                if item.qualified_name == qualified(self.module, (), target.id)
            ]
            if len(local) == 1:
                return target.id, local[0]
            if len(candidates) == 1:
                return target.id, candidates[0].qualified_name
            if candidates:
                return target.id, ""
            return None
        if not isinstance(target, ast.Attribute):
            return None
        name = target.attr
        candidates = self.functions_by_name.get(name, [])
        if not candidates:
            return None
        if isinstance(target.value, ast.Name) and target.value.id in {"self", "cls"} and self.class_scopes:
            candidate = qualified(self.module, self.class_scopes, name)
            if any(item.qualified_name == candidate for item in candidates):
                return name, candidate
        if (
            isinstance(target.value, ast.Call)
            and isinstance(target.value.func, ast.Name)
            and target.value.func.id == "super"
        ):
            return name, ""
        if len(candidates) == 1:
            return name, candidates[0].qualified_name
        return name, ""

    def visit_Call(self, node: ast.Call) -> None:
        resolved = self.resolve(node)
        if resolved is not None:
            name, qualified_name = resolved
            source = ast.get_source_segment(self.source, node) or ast.unparse(node)
            self.uses.append(ProjectUseData(
                name, source.strip(), node.lineno, str(self.path), qualified_name
            ))
        self.generic_visit(node)


def write_json(path: Path, values: Iterable[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps([value._asdict() for value in values], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def scan_project(root: Path) -> tuple[list[ParsedFile], int]:
    parsed: list[ParsedFile] = []
    parse_failures = 0
    for path in python_files(root):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, UnicodeError, SyntaxError, ValueError):
            parse_failures += 1
            continue
        parsed.append((path, module_name(root, path), source, tree))
    return parsed, parse_failures


def build_project_index(
    root: Path,
    data_dir: Path | None,
    *,
    parsed_files: list[ParsedFile] | None = None,
    parse_failures: int = 0,
) -> dict[str, int]:
    if parsed_files is None:
        parsed, parse_failures = scan_project(root)
    else:
        parsed = parsed_files

    functions: list[ProjectDefined] = []
    classes: list[ProjectClassDefine] = []
    classes_by_name: dict[str, list[str]] = defaultdict(list)
    for path, module, source, tree in parsed:
        visitor = DefinitionVisitor(module, path, source)
        visitor.visit(tree)
        functions.extend(visitor.functions)
        for name, values in visitor.class_names.items():
            classes_by_name[name].extend(values)
        classes.extend(extract_class_summary(
            str(path), source=source, tree=tree, collect=False
        ))

    functions_by_name: dict[str, list[ProjectDefined]] = defaultdict(list)
    for item in functions:
        functions_by_name[item.name].append(item)
    uses: list[ProjectUseData] = []
    for path, module, source, tree in parsed:
        visitor = UseVisitor(
            module, path, source, functions_by_name, classes_by_name
        )
        visitor.visit(tree)
        uses.extend(visitor.uses)

    if data_dir is None:
        return {"function_records": functions, "class_records": classes, "use_records": uses}
    write_json(data_dir / "project_function_defined.json", functions)
    write_json(data_dir / "project_class_defined.json", classes)
    write_json(data_dir / "project_function_use.json", uses)
    return {
        "files": len(parsed),
        "parse_failures": parse_failures,
        "functions": len(functions),
        "classes": len(classes),
        "uses": len(uses),
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: project_index.py PROJECT_ROOT")
    summary = build_project_index(Path(sys.argv[1]).resolve(), Path("data"))
    print(json.dumps(summary, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
