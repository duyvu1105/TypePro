import ast
from type_defined import ProjectDefined, ProjectClassDefine
from loguru import logger
import json
from textwrap import dedent
from typing import List
import os

FILE_PATH = "./testCode/example1.py"
project_data_path = "./data/project_class_defined.json"
project_path = "repos/alanjohnjames"
test_project_path = "./testCode"
total_class_data = []

import ast
from textwrap import dedent
from typing import List, Optional

def get_all_files(directory):
    file_paths = []
    for root, _, files in os.walk(directory):
        for file in files:
            full_path = os.path.join(root, file)
            if full_path.endswith((".py", ".pyi")):
                file_paths.append(full_path)

    return file_paths

def save_projects_to_json(projects: List[ProjectClassDefine], filename: str) -> None:
    projects_dict = [p._asdict() for p in projects]  # [1,6](@ref)

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(projects_dict, f, indent=4, ensure_ascii=False)  # [5,10](@ref)


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

def extract_class_summary(file_path: str) -> List[str]:
    with open(file_path, encoding="utf-8") as f:
        src = f.read()

    try:
        tree = ast.parse(src, filename=file_path)
    except:
        logger.error(f"ast.parse file error:{file_path}")
        tree = None
    if tree == None:
        return []
    summaries: List[str] = []

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
        summaries.append("\n".join(parts))
        temp_data = ProjectClassDefine(class_name, "\n".join(parts), file_path)
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
        summaries.append(signature)
        total_class_data.append(ProjectClassDefine(name, signature, file_path))

    return summaries


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

if __name__ == "__main__":
    import os
    from loguru import logger
    import time
    import sys

    args = sys.argv[1:]
    if len(args) == 0:
        logger.error("")
        sys.exit()
    target_dir = args[0]
    all_files = get_all_files(target_dir)
    for file in all_files:
        data = extract_class_summary(file)
    logger.info(len(total_class_data))
    logger.info(f"indexed class and alias definitions: {len(total_class_data)}")

    save_projects_to_json(total_class_data, project_data_path)
