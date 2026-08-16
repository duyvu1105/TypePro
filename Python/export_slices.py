"""Export TypePro Python slices and recommendations without calling an LLM.

Run this script from the repository's Python directory because the original
TypePro implementation resolves its data/ and Third-party-data/ paths there.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from slicing_code_class import Slicer
from function_methods import Function_methods


FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
ASSIGNMENT_NODES = (ast.Assign, ast.AnnAssign, ast.AugAssign)
BUILTIN_TYPE_NAMES = {
    "bool", "bytearray", "bytes", "classmethod", "complex", "dict", "enumerate",
    "filter", "float", "frozenset", "int", "list", "map", "memoryview", "object",
    "property", "range", "reversed", "set", "slice", "staticmethod", "str", "super",
    "tuple", "type", "zip", "none", "nonetype",
}
CLASS_NAME_RE = re.compile(r"(?m)^\s*class\s+([A-Za-z_]\w*)\b")
PACKAGE_RE = re.compile(r"(?m)^\s*#\s*package:\s*(\S+)")
MODULE_RE = re.compile(r"(?m)^\s*#\s*module:\s*(\S+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create TypePro contrastive-training records")
    parser.add_argument("--dataset", required=True, help="ManyTypes4Py/TypeGen-style JSON or JSONL")
    parser.add_argument("--repos-root", required=True, help="Root containing checked-out repositories")
    parser.add_argument("--output", required=True, help="Output JSONL")
    parser.add_argument("--rebuild-index", action="store_true", help="Run run_read_data.py once per project")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--parameters-only", action="store_true")
    parser.add_argument("--exclude-builtins", action="store_true")
    parser.add_argument("--log-every", type=int, default=100, help="Print progress every N annotations; 0 disables")
    return parser.parse_args()


def is_builtin_row(row: dict[str, Any]) -> bool:
    category = str(row.get("cat") or "").strip().casefold()
    if category in {"builtin", "builtins"}:
        return True
    original = str(row.get("origttype") or "").strip().casefold()
    if original.startswith("builtins."):
        return True
    if category or original:
        return False
    label = str(row.get("gttype") or row.get("processed_gttype") or "").strip()
    base = re.split(r"[\[<|, .]", label.replace("typing.", ""), maxsplit=1)[0].casefold()
    return base in BUILTIN_TYPE_NAMES


def recommendation_objects(definitions: Iterable[str]) -> list[dict[str, str]]:
    result = []
    seen = set()
    for definition in definitions:
        match = CLASS_NAME_RE.search(definition)
        if not match:
            continue
        name = match.group(1)
        package_match = PACKAGE_RE.search(definition)
        module_match = MODULE_RE.search(definition)
        package = package_match.group(1) if package_match else ""
        module = module_match.group(1) if module_match else ""
        qualified_name = f"{module}.{name}" if module else name
        key = qualified_name.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "name": name,
            "qualified_name": qualified_name,
            "package": package,
            "source": "third_party" if package else "project",
            "definition": definition,
        })
    return result


def read_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        with path.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, list):
        raise ValueError("Dataset must be a JSON list or JSONL")
    return value


def repository_parts(row: dict[str, Any]) -> tuple[str, ...]:
    url = str(row.get("url") or "").rstrip("/")
    if url:
        parts = url.split("/")
        if len(parts) >= 2:
            return parts[-2], parts[-1]
    file_parts = str(row.get("file") or "").replace("\\", "/").split("/")
    if "repos" in file_parts:
        index = file_parts.index("repos")
        if len(file_parts) > index + 2:
            return file_parts[index + 1], file_parts[index + 2]
    return (file_parts[0],) if file_parts else ("unknown",)


def resolve_file(row: dict[str, Any], repos_root: Path) -> Path:
    raw = Path(str(row.get("file") or row.get("path") or ""))
    if raw.is_file():
        return raw.resolve()
    normalized = str(raw).replace("\\", "/")
    if normalized.startswith("repos/"):
        normalized = normalized[len("repos/"):]
    candidate = repos_root / normalized
    if candidate.is_file():
        return candidate.resolve()
    repo = repos_root.joinpath(*repository_parts(row))
    # Some annotations store paths relative to the repository rather than repos/owner/repo.
    candidate = repo / str(row.get("path") or row.get("file") or "")
    if candidate.is_file():
        return candidate.resolve()
    raise FileNotFoundError(f"Cannot resolve source file for {row.get('file')}")


def add_parent_links(node: ast.AST, parent: ast.AST | None = None) -> None:
    if parent is not None:
        setattr(node, "parent", parent)
    for child in ast.iter_child_nodes(node):
        add_parent_links(child, node)


def enclosing_function_name(node: ast.AST) -> str:
    current = getattr(node, "parent", None)
    while current is not None:
        if isinstance(current, FUNCTION_NODES):
            return current.name
        current = getattr(current, "parent", None)
    return "global"


def assignment_names(node: ast.AST) -> list[str]:
    def target_names(target: ast.AST) -> Iterable[str]:
        if isinstance(target, ast.Name):
            yield target.id
        elif isinstance(target, ast.Attribute):
            yield ast.unparse(target)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                yield from target_names(element)

    if isinstance(node, ast.Assign):
        return [name for target in node.targets for name in target_names(target)]
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return list(target_names(node.target))
    return []


def masked_assignment(node: ast.AST) -> str:
    if isinstance(node, ast.Assign):
        targets = " = ".join(ast.unparse(target) for target in node.targets)
        return f"{targets}: <mask> = {ast.unparse(node.value)}"
    if isinstance(node, ast.AnnAssign):
        suffix = f" = {ast.unparse(node.value)}" if node.value is not None else ""
        return f"{ast.unparse(node.target)}: <mask>{suffix}"
    if isinstance(node, ast.AugAssign):
        return ast.unparse(node)
    raise TypeError(type(node).__name__)


def replace_statement(code_slice: str, original: str, masked: str, target_name: str) -> str:
    for source in (original, original.replace("'", '"'), original.replace('"', "'")):
        if source in code_slice:
            return code_slice.replace(source, masked, 1)
    plain = f"\n{target_name} = "
    return code_slice.replace(plain, f"\n{target_name}: <mask> = ", 1)


def export_one(
    row: dict[str, Any],
    file_path: Path,
    function_methods: Function_methods | None = None,
) -> dict[str, Any] | None:
    source = file_path.read_text(encoding="utf-8")
    root = ast.parse(source, filename=str(file_path))
    add_parent_links(root)
    target_name = str(row.get("name") or "")
    scope = str(row.get("scope") or "")
    local_function = str(row.get("loc") or "global").split("@")[0]
    slicer = Slicer(str(file_path), function_methods=function_methods)
    code_slice = ""

    if scope == "arg":
        for node in ast.walk(root):
            if not isinstance(node, FUNCTION_NODES) or node.name != local_function:
                continue
            parameters = list(getattr(node.args, "posonlyargs", [])) + list(node.args.args) + list(node.args.kwonlyargs)
            if node.args.vararg:
                parameters.append(node.args.vararg)
            if node.args.kwarg:
                parameters.append(node.args.kwarg)
            parameter = next((item for item in parameters if item.arg == target_name), None)
            if parameter is not None:
                parameter.annotation = ast.Name(id="mask", ctx=ast.Load())
                code_slice = slicer.slicing_params(node, root, target_name, str(file_path)).replace("mask", "<mask>")
                break
    elif scope == "return":
        for node in ast.walk(root):
            if isinstance(node, FUNCTION_NODES) and node.name == target_name:
                node.returns = ast.Name(id="mask", ctx=ast.Load())
                code_slice = slicer.slicing_func(node, root, str(file_path)).replace("mask", "<mask>")
                break
    else:
        for node in ast.walk(root):
            if not isinstance(node, ASSIGNMENT_NODES) or target_name not in assignment_names(node):
                continue
            if local_function != "global" and enclosing_function_name(node) != local_function:
                continue
            original = ast.unparse(node)
            sliced = slicer.slicing_var(node, root, str(file_path))
            code_slice = replace_statement(sliced, original, masked_assignment(node), target_name)
            break

    if not code_slice:
        return None
    result = dict(row)
    result["file"] = str(row.get("file") or row.get("path") or file_path)
    result["language"] = "python"
    result["interprocedural_slice"] = code_slice
    result["recommendation_types"] = recommendation_objects(slicer.get_type_recommend())
    result["other_prompt"] = list(slicer.get_other_prompt())
    return result


def main() -> None:
    args = parse_args()
    # The upstream repository does not ship these empty runtime directories.
    Path("data").mkdir(parents=True, exist_ok=True)
    Path("Third-party-data/dataset").mkdir(parents=True, exist_ok=True)
    rows = read_rows(Path(args.dataset))
    original_count = len(rows)
    if args.parameters_only:
        rows = [row for row in rows if str(row.get("scope") or "").casefold() == "arg"]
    if args.exclude_builtins:
        rows = [row for row in rows if not is_builtin_row(row)]
    if args.limit:
        rows = rows[: args.limit]
    repos_root = Path(args.repos_root).resolve()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    current_project: tuple[str, ...] | None = None
    function_methods: Function_methods | None = None
    written = failed = 0

    with output.open("w", encoding="utf-8") as handle:
        for index, row in enumerate(rows):
            try:
                project = repository_parts(row)
                if args.rebuild_index and project != current_project:
                    project_root = repos_root.joinpath(*project)
                    print(f"[export:index:start] project={'/'.join(project)}", flush=True)
                    subprocess.run([sys.executable, "run_read_data.py", str(project_root)], check=True)
                    print(f"[export:index:done] project={'/'.join(project)}", flush=True)
                    current_project = project
                    function_methods = Function_methods()
                elif function_methods is None:
                    function_methods = Function_methods()
                result = export_one(
                    row,
                    resolve_file(row, repos_root),
                    function_methods=function_methods,
                )
                if result is None:
                    failed += 1
                else:
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                    written += 1
            except Exception as error:  # Continue a long dataset export and retain actionable diagnostics.
                failed += 1
                print(f"[{index}] {row.get('file')}: {type(error).__name__}: {error}", file=sys.stderr)
            if args.log_every and ((index + 1) % args.log_every == 0 or index + 1 == len(rows)):
                print(
                    f"[export:progress] annotations={index + 1:,}/{len(rows):,} "
                    f"written={written:,} failed={failed:,}",
                    flush=True,
                )
    print(json.dumps({
        "input": original_count,
        "eligible": len(rows),
        "filtered": original_count - len(rows),
        "written": written,
        "failed": failed,
        "output": str(output),
    }))


if __name__ == "__main__":
    main()
