"""Build and query a self-contained knowledge base for one project.

The project KB is deliberately isolated: imported package records are copied
into the project's JSON instead of being queried from a process-wide catalog.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any, Iterable

from project_index import module_name, python_files


SCHEMA_VERSION = "typepro-project-kb-v1"
TYPE_WRAPPERS = {
    "Annotated", "Callable", "ClassVar", "Final", "Generic", "Literal",
    "Optional", "Protocol", "Type", "Union",
}


def dotted_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def annotation_types(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except (SyntaxError, ValueError):
            return [node.value]
    found = []
    for child in ast.walk(node):
        value = dotted_name(child) if isinstance(child, ast.Attribute) else (
            child.id if isinstance(child, ast.Name) else ""
        )
        leaf = value.rsplit(".", 1)[-1]
        if value and leaf not in TYPE_WRAPPERS and leaf not in {"Any", "None"}:
            found.append(value)
    # Attribute walks also visit their Name prefix; retain the most specific
    # spelling and remove stable duplicates.
    specific = []
    for value in sorted(set(found), key=lambda item: (-item.count("."), item)):
        if not any(other.endswith("." + value) for other in specific):
            specific.append(value)
    return specific


def record_key(record: dict[str, Any]) -> tuple[str, str]:
    return (
        str(record.get("kind") or "").casefold(),
        str(record.get("qualified_name") or record.get("name") or "").casefold(),
    )


def add_record(records: list[dict[str, Any]], seen: set[tuple[str, str]], record: dict[str, Any]) -> None:
    key = record_key(record)
    if key[1] and key not in seen:
        seen.add(key)
        records.append(record)


def imported_records(imports_dir: Path | None) -> list[dict[str, Any]]:
    if imports_dir is None or not imports_dir.is_dir():
        return []
    records = []
    for path in sorted(imports_dir.glob("*.json")):
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict) and value.get("name"):
                    item = dict(value)
                    item["source"] = item.get("source") or "imported"
                    item["kind"] = item.get("kind") or item.get("type") or "class"
                    records.append(item)
    return records


def build_project_kb(project_root: Path, imports_dir: Path | None = None) -> dict[str, Any]:
    root = project_root.resolve()
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    parse_failures = 0
    parsed: list[tuple[Path, str, str, ast.Module]] = []
    inferred_returns: dict[str, set[str]] = {}

    for path in python_files(root):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, UnicodeError, SyntaxError, ValueError):
            parse_failures += 1
            continue
        module = module_name(root, path)
        parsed.append((path, module, source, tree))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                qualified = ".".join(filter(None, (module, node.name)))
                definition = ast.get_source_segment(source, node) or ast.unparse(node)
                add_record(records, seen, {
                    "type": "class", "kind": "class", "name": node.name,
                    "qualified_name": qualified, "module": module,
                    "source": "project", "definition": definition[:16000],
                })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = ".".join(filter(None, (module, node.name)))
                returns = set(annotation_types(node.returns))
                for child in ast.walk(node):
                    if isinstance(child, ast.Return) and isinstance(child.value, ast.Call):
                        called = dotted_name(child.value.func)
                        if called and called.rsplit(".", 1)[-1][:1].isupper():
                            returns.add(called)
                inferred_returns[qualified] = returns
                signature = ast.unparse(node).splitlines()[0]
                add_record(records, seen, {
                    "type": "function", "kind": "function", "name": node.name,
                    "qualified_name": qualified, "module": module,
                    "source": "project", "definition": signature,
                    "return_types": sorted(returns),
                })
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if dotted_name(node.annotation).rsplit(".", 1)[-1] == "TypeAlias":
                    target = ast.unparse(node.value) if node.value else ""
                    qualified = ".".join(filter(None, (module, node.target.id)))
                    add_record(records, seen, {
                        "type": "alias", "kind": "type_alias", "name": node.target.id,
                        "qualified_name": qualified, "module": module,
                        "source": "project", "target": target,
                        "definition": f"{node.target.id}: TypeAlias = {target}",
                    })
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    local = alias.asname or alias.name
                    if alias.asname or path.stem == "__init__":
                        qualified = ".".join(filter(None, (module, local)))
                        target = f"{node.module}.{alias.name}"
                        add_record(records, seen, {
                            "type": "alias", "kind": "reexport_alias", "name": local,
                            "qualified_name": qualified, "module": module,
                            "source": "project", "target": target,
                            "definition": f"from {node.module} import {alias.name} as {local}",
                        })

    for item in imported_records(imports_dir):
        add_record(records, seen, item)

    # Return types are first-class KB entries even when only mentioned by a
    # function contract and absent from a scanned import package.
    for function_name, return_types in sorted(inferred_returns.items()):
        for value in sorted(return_types):
            name = value.rsplit(".", 1)[-1]
            if not name or not name.isidentifier():
                continue
            add_record(records, seen, {
                "type": "return_type", "kind": "function_return", "name": name,
                "qualified_name": value, "source": "project",
                "definition": f"class {name}:\n    # returned_by: {function_name}",
                "returned_by": function_name,
            })

    return {
        "schema_version": SCHEMA_VERSION,
        "project": root.name,
        "parse_failures": parse_failures,
        "record_count": len(records),
        "records": records,
    }


def candidate_records(kb: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = {"class", "type_alias", "reexport_alias", "function_return", "alias"}
    return [
        item for item in kb.get("records", [])
        if isinstance(item, dict) and item.get("name") and item.get("kind") in allowed
    ]


def top_project_types(
    kb: dict[str, Any], target_name: str, code_slice: str,
    seed_candidates: Iterable[dict[str, Any]] = (), limit: int = 10,
) -> list[dict[str, Any]]:
    """Rank only records contained in this project's KB."""
    seeds: dict[str, int] = {}
    for index, item in enumerate(seed_candidates):
        for value in (item.get("qualified_name"), item.get("name")):
            if value:
                seeds.setdefault(str(value).casefold(), index)
    target_tokens = set(re.findall(r"[A-Za-z_]\w*", target_name.casefold()))
    slice_tokens = set(re.findall(r"[A-Za-z_]\w*", code_slice.casefold()))
    ranked = []
    for item in candidate_records(kb):
        name = str(item["name"])
        qualified = str(item.get("qualified_name") or name)
        seed_rank = min(
            seeds.get(qualified.casefold(), 10_000),
            seeds.get(name.casefold(), 10_000),
        )
        words = set(re.findall(
            r"[A-Za-z_]\w*",
            f"{name} {qualified} {item.get('definition', '')}".casefold(),
        ))
        score = 0.0
        if seed_rank < 10_000:
            score += 10_000 - seed_rank
        score += 40 * len(target_tokens & words)
        score += min(25, len(slice_tokens & words))
        if name.casefold() in slice_tokens:
            score += 100
        ranked.append((-score, qualified.casefold(), item))
    ranked.sort(key=lambda value: (value[0], value[1]))
    result = []
    seen_names = set()
    for _, _, item in ranked:
        key = str(item.get("qualified_name") or item["name"]).casefold()
        if key in seen_names:
            continue
        seen_names.add(key)
        result.append({
            "name": str(item["name"]),
            "qualified_name": str(item.get("qualified_name") or item["name"]),
            "source": str(item.get("source") or "project"),
            "kind": str(item.get("kind") or "class"),
            "definition": str(item.get("definition") or item["name"]),
        })
        if len(result) >= limit:
            break
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Build one isolated TypePro project KB")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--imports-dir")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = build_project_kb(
        Path(args.project_root), Path(args.imports_dir) if args.imports_dir else None
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "output": str(output), "records": payload["record_count"],
        "parse_failures": payload["parse_failures"],
    }))


if __name__ == "__main__":
    main()
