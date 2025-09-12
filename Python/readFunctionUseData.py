from loguru import logger
import ast
from type_defined import ProjectUseData, ProjectDefined
import json
from typing import List
import os


project_data_path = "./data/project_function_defined.json"
project_use_path = "./data/project_function_use.json"
FILE_PATH = "./testCode/example1.py"
project_path = "repos/alanjohnjames"
test_project_path = "./testCode"

total_function_use_data = []
global project_function_data

def get_all_files(directory):
    file_paths = []
    for root, _, files in os.walk(directory): 
        for file in files:
            full_path = os.path.join(root, file)
            if full_path.endswith(".py"):
                file_paths.append(full_path)

    return file_paths

def is_project_function(fileName:str) -> bool:
    global project_function_data
    for i in project_function_data:
        if i.name == fileName:
            return True

    return False


def read_projects_from_json(filename: str) -> List[ProjectDefined]:
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            projects_data = json.load(f)

        return [ProjectDefined(**item) for item in projects_data]

    except FileNotFoundError:
        print(f"{filename} does not exist")
        return []
    except json.JSONDecodeError:
        print(f"{filename} Not a valid JSON format")
        return []

def save_projects_to_json(projects: List[ProjectUseData], filename: str) -> None:

    projects_dict = [p._asdict() for p in projects]  # [1,6](@ref)

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(projects_dict, f, indent=4, ensure_ascii=False)  # [5,10](@ref)


def list_function_calls(file_path: str) -> None:

    logger.debug(f"read function use file:{file_path}")
    with open(file_path, encoding="utf-8") as f:
        src = f.read()
    try:
        tree = ast.parse(src)
    except:
        tree = None
    if tree!=None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    func_name = func.id
                elif isinstance(func, ast.Attribute):
                    func_name = func.attr
                else:
                    continue

                src_code = ast.get_source_segment(src, node).strip()

                lineno = node.lineno

                if is_project_function(func_name):
                    temp_data = ProjectUseData(func_name, src_code, lineno, file_path)
                    total_function_use_data.append(temp_data)


if __name__ == "__main__":

    project_function_data = read_projects_from_json(project_data_path)

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
        list_function_calls(file)

    logger.info(len(total_function_use_data))

    save_projects_to_json(total_function_use_data, project_use_path)