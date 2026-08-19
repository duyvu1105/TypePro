"""Export TypePro Python slices and recommendations without calling an LLM.

Run this script from the repository's Python directory because the original
TypePro implementation resolves its data/ and Third-party-data/ paths there.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import signal
import sys
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from slicing_code_class import ProjectAnalysisCache, Slicer
from function_methods import Function_methods
from project_index import build_project_index, scan_project


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
SOURCE_RE = re.compile(r"(?m)^\s*#\s*source:\s*(\S+)")
KIND_RE = re.compile(r"(?m)^\s*#\s*kind:\s*(\S+)")


class AnnotationTimeoutError(BaseException):
    """Control-flow exception that ordinary analysis error handlers must not swallow."""

    pass


@contextmanager
def annotation_deadline(seconds: int):
    """Interrupt one annotation on Linux without losing the process caches."""
    if seconds <= 0:
        yield
        return
    if not all(hasattr(signal, name) for name in ("SIGALRM", "setitimer", "ITIMER_REAL")):
        raise RuntimeError("Per-annotation timeout requires POSIX setitimer support")

    def handle_timeout(_signum, _frame):
        raise AnnotationTimeoutError(
            f"annotation exceeded the {seconds}-second deadline"
        )

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


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
    parser.add_argument(
        "--trace-every", type=int, default=0,
        help="Print detailed per-annotation timings every N annotations; 0 disables",
    )
    parser.add_argument(
        "--annotation-timeout-seconds",
        type=int,
        default=0,
        help="Skip one annotation after this many seconds; 0 disables",
    )
    parser.add_argument(
        "--project-analysis-timeout-seconds",
        type=int,
        default=0,
        help="Fall back to file-local slicing if project indexing exceeds this deadline",
    )
    args = parser.parse_args()
    if args.annotation_timeout_seconds < 0:
        parser.error("--annotation-timeout-seconds must be >= 0")
    if args.project_analysis_timeout_seconds < 0:
        parser.error("--project-analysis-timeout-seconds must be >= 0")
    if args.trace_every < 0:
        parser.error("--trace-every must be >= 0")
    return args


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
        source_match = SOURCE_RE.search(definition)
        kind_match = KIND_RE.search(definition)
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
            "source": (
                source_match.group(1)
                if source_match else ("third_party" if package else "project")
            ),
            "kind": kind_match.group(1) if kind_match else "class",
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
    analysis_cache: ProjectAnalysisCache | None = None,
) -> dict[str, Any] | None:
    export_started = time.monotonic()
    parse_started = export_started
    source = file_path.read_text(encoding="utf-8")
    root = ast.parse(source, filename=str(file_path))
    add_parent_links(root)
    parse_seconds = time.monotonic() - parse_started
    target_name = str(row.get("name") or "")
    scope = str(row.get("scope") or "")
    local_function = str(row.get("loc") or "global").split("@")[0]
    slicer = Slicer(
        str(file_path),
        function_methods=function_methods,
        analysis_cache=analysis_cache,
    )
    analyzer_seconds = time.monotonic() - parse_started - parse_seconds
    code_slice = ""
    slicing_started = time.monotonic()

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
    slicing_seconds = time.monotonic() - slicing_started
    result = dict(row)
    result["file"] = str(row.get("file") or row.get("path") or file_path)
    result["language"] = "python"
    result["interprocedural_slice"] = code_slice
    recommendations = recommendation_objects(slicer.get_type_recommend())
    result["recommendation_types"] = recommendations
    result["recommendation_diagnostics"] = {
        "count": len(recommendations),
        "by_source": dict(Counter(item["source"] for item in recommendations)),
        "by_kind": dict(Counter(item["kind"] for item in recommendations)),
        "timings_seconds": {
            "read_parse_target": round(parse_seconds, 6),
            "file_import_analyzer": round(analyzer_seconds, 6),
            "slice_and_retrieval": round(slicing_seconds, 6),
            **{
                name: round(seconds, 6)
                for name, seconds in slicer.retrieval_timings.items()
            },
            "export_total": round(time.monotonic() - export_started, 6),
        },
        "retrieval_counts": dict(slicer.retrieval_counts),
    }
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
    analysis_cache: ProjectAnalysisCache | None = None
    written = failed = timed_out = 0

    with output.open("w", encoding="utf-8") as handle:
        for index, row in enumerate(rows):
            try:
                project = repository_parts(row)
                if args.rebuild_index and project != current_project:
                    if analysis_cache is not None:
                        print(f"[export:cache] {analysis_cache.summary()}", flush=True)
                    project_root = repos_root.joinpath(*project)
                    index_started = time.monotonic()
                    print(f"[export:index:start] project={'/'.join(project)}", flush=True)
                    try:
                        with annotation_deadline(
                            args.project_analysis_timeout_seconds
                        ):
                            parsed_files, parse_failures = scan_project(project_root)
                            index_summary = build_project_index(
                                project_root,
                                Path("data"),
                                parsed_files=parsed_files,
                                parse_failures=parse_failures,
                            )
                            print(
                                f"[export:index:done] project={'/'.join(project)} "
                                f"files={index_summary['files']} "
                                f"parse_failures={index_summary['parse_failures']} "
                                f"seconds={time.monotonic() - index_started:.1f}",
                                flush=True,
                            )
                            analysis_started = time.monotonic()
                            print(
                                f"[export:project-analysis:start] project={'/'.join(project)}",
                                flush=True,
                            )
                            function_methods = Function_methods(
                                str(project_root), parsed_files=parsed_files
                            )
                    except AnnotationTimeoutError:
                        function_methods = Function_methods.empty()
                        print(
                            "[export:project-analysis:timeout] "
                            f"project={'/'.join(project)} "
                            f"seconds={args.project_analysis_timeout_seconds} "
                            "fallback=file-local",
                            file=sys.stderr,
                            flush=True,
                        )
                        analysis_started = time.monotonic()
                    current_project = project
                    analysis_cache = ProjectAnalysisCache()
                    print(
                        f"[export:project-analysis:done] project={'/'.join(project)} "
                        f"functions={len(function_methods.total_function_data)} "
                        f"function_uses={len(function_methods.total_function_use_data)} "
                        f"classes={len(function_methods.total_class_data)} "
                        f"seconds={time.monotonic() - analysis_started:.1f}",
                        flush=True,
                    )
                elif function_methods is None:
                    function_methods = Function_methods()
                    analysis_cache = ProjectAnalysisCache()
                trace_annotation = bool(
                    args.trace_every
                    and (index % args.trace_every == 0 or index + 1 == len(rows))
                )
                annotation_started = time.monotonic()
                if trace_annotation:
                    print(
                        f"[export:annotation:start] index={index + 1}/{len(rows)} "
                        f"file={row.get('file')!r} name={row.get('name')!r}",
                        flush=True,
                    )
                with annotation_deadline(args.annotation_timeout_seconds):
                    result = export_one(
                        row,
                        resolve_file(row, repos_root),
                        function_methods=function_methods,
                        analysis_cache=analysis_cache,
                    )
                if result is None:
                    failed += 1
                else:
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                    written += 1
                if trace_annotation:
                    diagnostics = (
                        result.get("recommendation_diagnostics", {})
                        if result is not None else {}
                    )
                    print(
                        "[export:annotation:done] "
                        f"index={index + 1}/{len(rows)} written={result is not None} "
                        f"candidates={diagnostics.get('count', 0)} "
                        f"seconds={time.monotonic() - annotation_started:.3f} "
                        f"timings={json.dumps(diagnostics.get('timings_seconds', {}), sort_keys=True)} "
                        f"retrieval_counts={json.dumps(diagnostics.get('retrieval_counts', {}), sort_keys=True)}",
                        flush=True,
                    )
            except AnnotationTimeoutError as error:
                failed += 1
                timed_out += 1
                print(
                    f"[annotation:timeout] index={index} "
                    f"seconds={args.annotation_timeout_seconds} "
                    f"file={row.get('file')!r} name={row.get('name')!r}: {error}",
                    file=sys.stderr,
                    flush=True,
                )
            except Exception as error:  # Continue a long dataset export and retain actionable diagnostics.
                failed += 1
                print(
                    f"[export:annotation:error] index={index + 1}/{len(rows)} "
                    f"file={row.get('file')!r} name={row.get('name')!r} "
                    f"error={type(error).__name__}: {error}",
                    file=sys.stderr,
                    flush=True,
                )
            if args.log_every and ((index + 1) % args.log_every == 0 or index + 1 == len(rows)):
                print(
                    f"[export:progress] annotations={index + 1:,}/{len(rows):,} "
                    f"written={written:,} failed={failed:,}",
                    flush=True,
                )
    if analysis_cache is not None:
        print(f"[export:cache] {analysis_cache.summary()}", flush=True)
    print(json.dumps({
        "input": original_count,
        "eligible": len(rows),
        "filtered": original_count - len(rows),
        "written": written,
        "failed": failed,
        "timed_out": timed_out,
        "annotation_timeout_seconds": args.annotation_timeout_seconds,
        "output": str(output),
    }))


if __name__ == "__main__":
    main()
