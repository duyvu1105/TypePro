"""Class and alias summaries shared by project indexing and retrieval."""
import ast
from textwrap import dedent
from typing import List, Optional

from loguru import logger
from typepro.analysis.type_defined import ProjectClassDefine

total_class_data = []

def get_method_signature(source: str, fn: ast.FunctionDef) -> str:

    params = []
    args = fn.args
    # posonlyargs (3.8+)
    for a in getattr(args, "posonlyargs", []):
        params.append(a.arg)
    # normal args
    for a in args.args:
        params.append(a.arg)
    # vararg
    if args.vararg:
        params.append(f"*{args.vararg.arg}")
    # kwonlyargs
    for a in args.kwonlyargs:
        params.append(f"{a.arg}")
    # kwarg
    if args.kwarg:
        params.append(f"**{args.kwarg.arg}")

    param_list = ", ".join(params)
    ret = ""
    if fn.returns:
        try:
            ret = ast.unparse(fn.returns)
        except Exception:
            ret = ast.get_source_segment(source, fn.returns) or ""
        ret = f" -> {ret}"
    return f"def {fn.name}({param_list}){ret}:"

def extract_class_summary(
    file_path: str,
    source: str | None = None,
    tree: ast.Module | None = None,
    *,
    collect: bool = True,
) -> List[ProjectClassDefine]:
    if source is None:
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
    src = source
    if tree is None:
        try:
            tree = ast.parse(src, filename=file_path)
        except (SyntaxError, ValueError):
            logger.error(f"ast.parse file error:{file_path}")
    if tree == None:
        return []
    definitions: List[ProjectClassDefine] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        sig_lines = []
        for deco in node.decorator_list:
            deco_src = ast.get_source_segment(src, deco) or ""
            sig_lines.append(f"@{deco_src.strip()}")
        # bases + keywords
        bases = []
        for b in node.bases:
            try: bases.append(ast.unparse(b))
            except: bases.append(ast.get_source_segment(src, b).strip())
        for kw in node.keywords:
            if kw.arg:
                try: val = ast.unparse(kw.value)
                except: val = ast.get_source_segment(src, kw.value).strip()
                bases.append(f"{kw.arg}={val}")
            else:
                try: bases.append(f"**{ast.unparse(kw.value)}")
                except: bases.append("**" + ast.get_source_segment(src, kw.value).strip())
        base_list = f"({', '.join(bases)})" if bases else ""
        sig_lines.append(f"class {node.name}{base_list}:")
        class_name = node.name

        fields: List[str] = []
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                targets = []
                for t in stmt.targets:
                    try: targets.append(ast.unparse(t))
                    except: targets.append(ast.get_source_segment(src, t).strip())
                val = ast.get_source_segment(src, stmt.value).strip()
                fields.append(f"{', '.join(targets)} = {val}")
            elif isinstance(stmt, ast.AnnAssign):
                target = stmt.target
                try: name = ast.unparse(target)
                except: name = ast.get_source_segment(src, target).strip()
                ann = stmt.annotation
                try: at = ast.unparse(ann)
                except: at = ast.get_source_segment(src, ann).strip()
                if stmt.value:
                    val = ast.get_source_segment(src, stmt.value).strip()
                    fields.append(f"{name}: {at} = {val}")
                else:
                    fields.append(f"{name}: {at}")

        methods: List[str] = []
        for stmt in node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(get_method_signature(src, stmt))

        parts = sig_lines
        if fields:
            parts.append("    # fields")
            for f in fields:
                parts.append(f"    {f}")
        if methods:
            parts.append("    # methods")
            for m in methods:
                parts.append(f"    {m}")
        temp_data = ProjectClassDefine(class_name, "\n".join(parts), file_path)
        definitions.append(temp_data)
        if collect:
            total_class_data.append(temp_data)

    # Type aliases participate in retrieval even though the legacy index only
    # stored concrete classes. Render them as class-like definitions so the
    # existing recommendation/export format remains backward compatible.
    for node in tree.body:
        alias = extract_type_alias(node)
        if alias is None:
            continue
        name, value = alias
        signature = f"class {name}:\n    # type alias: {value}"
        definition = ProjectClassDefine(name, signature, file_path)
        definitions.append(definition)
        if collect:
            total_class_data.append(definition)

    return definitions


def extract_type_alias(node: ast.AST) -> tuple[str, str] | None:
    target = value = annotation = None
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        target, value = node.target.id, node.value
        annotation = ast.unparse(node.annotation)
    elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        target, value = node.targets[0].id, node.value
    if not target or value is None:
        return None
    type_like_name = target.lstrip("_")[:1].isupper()
    recognized = bool(annotation and annotation.endswith("TypeAlias")) or (
        type_like_name and isinstance(value, (ast.Subscript, ast.Attribute, ast.BinOp))
    )
    if isinstance(value, ast.Call):
        recognized = type_like_name and ast.unparse(value.func).split(".")[-1] in {
            "NewType", "TypeVar", "ParamSpec", "TypeVarTuple"
        }
    if isinstance(value, ast.Name):
        recognized = bool(annotation and annotation.endswith("TypeAlias"))
    return (target, ast.unparse(value)) if recognized else None
