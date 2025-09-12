import ast
from type_defined import ProjectDefined
from loguru import logger
import json
from typing import List
import os

FILE_PATH = "./testCode/example1.py"
test_project_path = "./testCode"
project_data_path = "./data/project_function_defined.json"
project_path = "./repos/kavyamahesh"

total_function_data = []

def get_all_files(directory):
    file_paths = []
    for root, _, files in os.walk(directory):  
        for file in files:
            full_path = os.path.join(root, file)  
            if full_path.endswith(".py"):
                file_paths.append(full_path)

    return file_paths


def has_type_annotations(func_node: ast.FunctionDef) -> bool:
    if func_node.returns is not None:
        return True

    args = func_node.args
    for arg in getattr(args, "posonlyargs", []):
        if arg.annotation is not None:
            return True
    for arg in args.args:
        if arg.annotation is not None:
            return True
    if args.vararg and args.vararg.annotation is not None:
        return True
    for arg in args.kwonlyargs:
        if arg.annotation is not None:
            return True
    if args.kwarg and args.kwarg.annotation is not None:
        return True

    return False


def list_functions(file_path: str):

    with open(file_path, 'r', encoding='utf-8') as f:
        source = f.read()
    try:
        tree = ast.parse(source)
    except:
        logger.error(f"ast.parse file error:{file_path}")
        tree = None

    def format_args(args_node: ast.arguments) -> list:
        params = []
        defaults = [None] * (len(args_node.args) - len(args_node.defaults)) + args_node.defaults
        for arg, default in zip(args_node.args, defaults):
            name = arg.arg
            if arg.annotation:
                name += f": {ast.unparse(arg.annotation)}"
            if default:
                name += f" = {ast.unparse(default)}"
            params.append(name)
        if args_node.vararg:
            var = args_node.vararg.arg
            if args_node.vararg.annotation:
                var += f": {ast.unparse(args_node.vararg.annotation)}"
            params.append(f"*{var}")
        for kwarg, default in zip(args_node.kwonlyargs, args_node.kw_defaults):
            name = kwarg.arg
            if kwarg.annotation:
                name += f": {ast.unparse(kwarg.annotation)}"
            if default:
                name += f" = {ast.unparse(default)}"
            params.append(name)
        if args_node.kwarg:
            kw = args_node.kwarg.arg
            if args_node.kwarg.annotation:
                kw += f": {ast.unparse(args_node.kwarg.annotation)}"
            params.append(f"**{kw}")
        return params

    signatures = []
    if tree != None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):

                name = node.name
                params = format_args(node.args)
                sig = f"{name}({', '.join(params)})"
                if node.returns:
                    sig += f" -> {ast.unparse(node.returns)}"
                signatures.append((node.lineno, sig))
                if not has_type_annotations(node):
                    temp_data = ProjectDefined(name, ast.get_source_segment(source, node))
                else:
                    temp_data = ProjectDefined(name, "function " + sig)

                total_function_data.append(temp_data)



def save_projects_to_json(projects: List[ProjectDefined], filename: str) -> None:

    projects_dict = [p._asdict() for p in projects]  # [1,6](@ref)

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(projects_dict, f, indent=4, ensure_ascii=False)  # [5,10](@ref)

def main():
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
        list_functions(file)
    save_projects_to_json(total_function_data, project_data_path)


if __name__ == '__main__':
    main()
