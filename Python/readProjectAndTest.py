import os
import ast
from loguru import logger
from typing import List, Union, Tuple, Dict
# from SlicingMethods import slicing_var, slicing_func, slicing_params, get_lhs, load_data
from slicing_code_class import Slicer
from LLMAgent import GPT_Client


VarDeclNode = Union[ast.Assign, ast.AnnAssign]

def find_variable_declarations(file_path: str) -> List[VarDeclNode]:
    with open(file_path, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, filename=file_path)

    decls: List[VarDeclNode] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            valid = True
            for t in node.targets:
                if not isinstance(t, (ast.Name, ast.Tuple, ast.List)):
                    valid = False
            if valid:
                decls.append(node)

        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                decls.append(node)

    return decls, tree

def set_return_annotation(
    node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
    annotation_str: str
) -> None:

    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise TypeError(f"Expected FunctionDef or AsyncFunctionDef, got {type(node).__name__}")

    expr_ast = ast.parse(annotation_str, mode='eval').body  # type: ignore

    node.returns = expr_ast

def set_param_annotation(
    node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
    param_name: str,
    annotation_str: str
) -> None:

    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise TypeError(f"Expected FunctionDef or AsyncFunctionDef, got {type(node).__name__}")

    ann_expr = ast.parse(annotation_str, mode='eval').body  # type: ignore

    def try_set(arg: ast.arg):
        if arg.arg == param_name:
            arg.annotation = ann_expr

    for arg in node.args.args:
        try_set(arg)

    for arg in node.args.kwonlyargs:
        try_set(arg)

    if node.args.vararg and node.args.vararg.arg == param_name:
        node.args.vararg.annotation = ann_expr

    if node.args.kwarg and node.args.kwarg.arg == param_name:
        node.args.kwarg.annotation = ann_expr

def get_all_files(directory):

    file_paths = []
    for root, _, files in os.walk(directory):
        for file in files:
            full_path = os.path.join(root, file)
            if full_path.endswith(".py"):
                file_paths.append(full_path)

    return file_paths


def collect_function_defs_from_dir(file_path: str) -> List[Tuple[str, ast.FunctionDef]]:

    func_defs: List[ast.FunctionDef] = []

    try:
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=file_path)
    except (SyntaxError, UnicodeDecodeError):

        logger.warning(f"filed:{file_path}")

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            func_defs.append(node)

    return func_defs, tree


def extract_function_params(file_path: str) -> Dict[ast.FunctionDef, List[str]]:

    with open(file_path, encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source, filename=file_path)
    func_params: Dict[ast.FunctionDef, List[str]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            params: List[str] = []
            args = node.args

            params.extend(arg.arg for arg in getattr(args, 'posonlyargs', []))

            params.extend(arg.arg for arg in args.args)

            if args.vararg:
                params.append(f"*{args.vararg.arg}")

            params.extend(arg.arg for arg in args.kwonlyargs)

            if args.kwarg:
                params.append(f"**{args.kwarg.arg}")

            func_params[node] = params

    return func_params, tree

def annotate_assign(assign_node: ast.Assign, type_str: str) -> ast.AnnAssign:

    annotation = ast.Name(id=type_str, ctx=ast.Load())
    return ast.AnnAssign(
        target=assign_node.targets[0],
        annotation=annotation,
        value=assign_node.value,
        simple=1
    )

def modify_annotation(node: Union[ast.Assign, ast.AnnAssign], type_str: str) -> str:

    if isinstance(node, ast.Assign):
        new_node = annotate_assign(node, type_str)
    elif isinstance(node, ast.AnnAssign):
        new_node = ast.AnnAssign(
            target=node.target,
            annotation=ast.Name(id=type_str, ctx=ast.Load()),
            value=node.value,
            simple=getattr(node, 'simple', 1)
        )
    else:
        raise TypeError("filed")

    ast.fix_missing_locations(new_node)

    mod = ast.Module(body=[new_node], type_ignores=[])
    ast.fix_missing_locations(mod)
    return ast.unparse(mod.body[0])


def strip_type_annotations(node: ast.AST) -> ast.AST:
    if isinstance(node, ast.AnnAssign):

        new_assign = ast.Assign(
            targets=[node.target],
            value=node.value or ast.Constant(value=None),
            lineno=node.lineno,
            col_offset=node.col_offset,
            end_lineno=getattr(node, "end_lineno", None),
            end_col_offset=getattr(node, "end_col_offset", None),
        )
        return ast.copy_location(new_assign, node)

    if isinstance(node, ast.FunctionDef):
        node.returns = None
        for arg in node.args.args + node.args.kwonlyargs:
            arg.annotation = None
        if node.args.vararg:
            node.args.vararg.annotation = None
        if node.args.kwarg:
            node.args.kwarg.annotation = None
        return node

    if isinstance(node, ast.AsyncFunctionDef):
        node.returns = None
        for arg in node.args.args + node.args.kwonlyargs:
            arg.annotation = None
        if node.args.vararg:
            node.args.vararg.annotation = None
        if node.args.kwarg:
            node.args.kwarg.annotation = None
        return node

    return node

if __name__ == "__main__":
   pass