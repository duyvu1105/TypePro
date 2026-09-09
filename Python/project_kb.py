"""Build and query a self-contained knowledge base for one project.

The project KB is deliberately isolated: imported package records are copied
into the project's JSON instead of being queried from a process-wide catalog.
"""
from __future__ import annotations

import argparse
import ast
import copy
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

from project_index import module_name, python_files
from target_context import MASK, mask_definition


SCHEMA_VERSION = "typepro-project-kb-v3-target-member-index"
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
        if value and leaf not in TYPE_WRAPPERS and leaf not in {"Any", "None", MASK}:
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


def class_member_metadata(node: ast.ClassDef) -> dict[str, list[str]]:
    """Collect member names only; annotations never become retrieval signals."""
    methods: set[str] = set()
    fields: set[str] = set()
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.add(child.name)
            for statement in ast.walk(child):
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and statement is not child:
                    continue
                targets: list[ast.AST] = []
                if isinstance(statement, ast.Assign):
                    targets = list(statement.targets)
                elif isinstance(statement, ast.AnnAssign):
                    targets = [statement.target]
                for target in targets:
                    for item in ast.walk(target):
                        if (
                            isinstance(item, ast.Attribute)
                            and isinstance(item.value, ast.Name)
                            and item.value.id in {"self", "cls"}
                        ):
                            fields.add(item.attr)
        elif isinstance(child, (ast.Assign, ast.AnnAssign)):
            targets = child.targets if isinstance(child, ast.Assign) else [child.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    fields.add(target.id)
    return {
        "declared_methods": sorted(methods),
        "declared_fields": sorted(fields),
        "bases": sorted(filter(None, (dotted_name(base) for base in node.bases))),
    }


def resolve_inherited_members(records: list[dict[str, Any]]) -> None:
    classes = [item for item in records if item.get("kind") == "class"]
    by_qualified = {str(item.get("qualified_name")): item for item in classes}
    by_leaf: dict[str, list[dict[str, Any]]] = {}
    for item in classes:
        by_leaf.setdefault(str(item.get("name")), []).append(item)

    def resolve_base(item: dict[str, Any], base: str) -> dict[str, Any] | None:
        if base in by_qualified:
            return by_qualified[base]
        module = str(item.get("module") or "")
        local = f"{module}.{base}" if module else base
        if local in by_qualified:
            return by_qualified[local]
        matches = by_leaf.get(base.rsplit(".", 1)[-1], [])
        return matches[0] if len(matches) == 1 else None

    for item in classes:
        members = set(item.get("declared_methods", ())) | set(item.get("declared_fields", ()))
        pending = list(item.get("bases", ()))
        visited = set()
        while pending:
            base = pending.pop()
            parent = resolve_base(item, base)
            if parent is None:
                continue
            key = str(parent.get("qualified_name"))
            if key in visited:
                continue
            visited.add(key)
            members.update(parent.get("declared_methods", ()))
            members.update(parent.get("declared_fields", ()))
            pending.extend(parent.get("bases", ()))
        item["members"] = sorted(members)


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


def build_project_kb(project_root: Path, imports_dir: Path | None = None, *, parsed_files=None, external_records=()) -> dict[str, Any]:
    root = project_root.resolve()
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    parse_failures = 0
    parsed: list[tuple[Path, str, str, ast.Module]] = []
    inferred_returns: dict[str, set[str]] = {}

    if parsed_files is None:
        from project_index import scan_project
        parsed, parse_failures = scan_project(root)
    else:
        parsed = parsed_files
    for path, module, source, tree in parsed:
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                qualified = ".".join(filter(None, (module, node.name)))
                definition = ast.get_source_segment(source, node) or ast.unparse(node)
                add_record(records, seen, {
                    "type": "class", "kind": "class", "name": node.name,
                    "qualified_name": qualified, "module": module,
                    "source": "project", "definition": definition[:16000],
                    **class_member_metadata(node),
                })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = ".".join(filter(None, (module, node.name)))
                # A return annotation is a label for some samples.  Never let
                # it create a candidate, rank signal, or KB signature.  A
                # concrete constructor in the function body remains valid
                # source-level evidence, for example ``return User()``.
                returns: set[str] = set()
                for child in ast.walk(node):
                    if isinstance(child, ast.Return) and isinstance(child.value, ast.Call):
                        called = dotted_name(child.value.func)
                        if called and called.rsplit(".", 1)[-1][:1].isupper():
                            returns.add(called)
                inferred_returns[qualified] = returns
                signature_node = copy.deepcopy(node)
                signature_node.returns = None
                signature = ast.unparse(signature_node).splitlines()[0]
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

    for item in [*imported_records(imports_dir), *external_records]:
        add_record(records, seen, item)

    resolve_inherited_members(records)

    # Return types inferred from executable function bodies are first-class KB
    # entries even when absent from a scanned import package.  Annotation-only
    # types are intentionally excluded above.
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
    *, target_function: str = "", target_scope: str = "",
    target_members: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Rank project-KB records without reading the target annotation."""
    seeds: dict[str, int] = {}
    for index, item in enumerate(seed_candidates):
        for value in (item.get("qualified_name"), item.get("name")):
            if value:
                seeds.setdefault(str(value).casefold(), index)
    target_tokens = set(re.findall(r"[A-Za-z_]\w*", target_name.casefold()))
    slice_tokens = set(re.findall(r"[A-Za-z_]\w*", code_slice.casefold()))
    ranked = []
    member_query = set((target_members or {}).get("methods", ())) | set(
        (target_members or {}).get("attributes", ())
    )
    member_frequency: dict[str, int] = {}
    class_records = [item for item in candidate_records(kb) if item.get("kind") == "class"]
    for member in member_query:
        member_frequency[member] = sum(member in item.get("members", ()) for item in class_records)
    member_ranked = []
    for item in candidate_records(kb):
        name = str(item["name"])
        qualified = str(item.get("qualified_name") or name)
        definition = str(item.get("definition") or name)
        if target_function and target_scope:
            definition = mask_definition(
                definition, target_function, target_name, target_scope
            )
        seed_rank = min(
            seeds.get(qualified.casefold(), 10_000),
            seeds.get(name.casefold(), 10_000),
        )
        words = set(re.findall(
            r"[A-Za-z_]\w*",
            f"{name} {qualified} {definition}".casefold(),
        ))
        score = 0.0
        if seed_rank < 10_000:
            score += 10_000 - seed_rank
        score += 40 * len(target_tokens & words)
        score += min(25, len(slice_tokens & words))
        if name.casefold() in slice_tokens:
            score += 100
        ranked.append((-score, qualified.casefold(), item, definition))
        matched = member_query & set(item.get("members", ()))
        method_matches = set((target_members or {}).get("methods", ())) & matched
        rare_attribute = any(
            member_frequency.get(member, len(class_records)) <= max(3, len(class_records) // 50)
            for member in matched
        )
        eligible = bool(method_matches or len(matched) >= 2 or rare_attribute)
        if eligible:
            member_score = sum(
                1.0 + math.log((len(class_records) + 1) / (member_frequency[member] + 1))
                for member in matched
            )
            member_ranked.append((-member_score, -len(matched), qualified.casefold(), item, definition))
    ranked.sort(key=lambda value: (value[0], value[1]))
    member_ranked.sort(key=lambda value: value[:3])
    result = []
    seen_names = set()
    # Preserve most of the existing list while allowing strong target-member
    # evidence to contribute at most two candidates.
    combined = [(item, definition) for *_, item, definition in member_ranked[:2]]
    combined.extend((item, definition) for _, _, item, definition in ranked)
    for item, definition in combined:
        key = str(item.get("qualified_name") or item["name"]).casefold()
        if key in seen_names:
            continue
        seen_names.add(key)
        result.append({
            "name": str(item["name"]),
            "qualified_name": str(item.get("qualified_name") or item["name"]),
            "source": str(item.get("source") or "project"),
            "kind": str(item.get("kind") or "class"),
            "definition": definition,
        })
        if len(result) >= limit:
            break
    return result


def target_member_query(function: ast.AST | None, target_name: str) -> dict[str, list[str]]:
    """Extract members accessed through the target and simple definite aliases."""
    if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return {"methods": [], "attributes": []}
    aliases = {target_name}
    methods: set[str] = set()
    attributes: set[str] = set()

    def root_member(node: ast.Attribute) -> tuple[str, str] | None:
        current: ast.AST = node
        chain = []
        while isinstance(current, ast.Attribute):
            chain.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name) and current.id in aliases and chain:
            return current.id, chain[-1]
        return None

    class Uses(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            if node is function:
                self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node):
            return

        def visit_Lambda(self, node):
            return

        def visit_Call(self, node):
            if isinstance(node.func, ast.Attribute):
                found = root_member(node.func)
                if found:
                    methods.add(found[1])
            self.generic_visit(node)

        def visit_Attribute(self, node):
            found = root_member(node)
            if found:
                attributes.add(found[1])
            self.generic_visit(node)

    visitor = Uses()
    for statement in function.body:
        visitor.visit(statement)
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            value = statement.value
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    if isinstance(value, ast.Name) and value.id in aliases:
                        aliases.add(target.id)
                    else:
                        aliases.discard(target.id)
    attributes.difference_update(methods)
    return {"methods": sorted(methods), "attributes": sorted(attributes)}


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
