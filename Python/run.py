import json
from typing import List, Dict, Union
import re
from tool import wrap_with_union,convert_type_annotation, split_unpack_in_code, attribute_to_string
from type_defined import OutPutData
from hityper.typeobject import TypeObject
import time
JsonDataEntry = Dict[str, Union[str, bool, int, None]]
JsonData = List[JsonDataEntry]

import os
import ast
from loguru import logger
from typing import List, Union, Tuple, Dict
# from SlicingMethods import slicing_var, slicing_func, slicing_params, get_lhs, load_data
from slicing_code_class import Slicer
from LLMAgent import GPT_Client

total_out_data:List[OutPutData] = []
output_fs_path = "./Output/"
api_key = "sk-xxxx"
dataset_path = "./data/test.json"

VarDeclNode = Union[ast.Assign, ast.AnnAssign]

def extract_target_names(target: ast.AST) -> List[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    elif isinstance(target, (ast.Tuple, ast.List)):
        names: List[str] = []
        for elt in target.elts:
            names.extend(extract_target_names(elt))
        return names
    elif isinstance(target, ast.Attribute):
        return [attribute_to_string(target)]
    else:
        return []
def get_assign_targets(code: str) -> List[str]:
    tree = ast.parse(split_unpack_in_code(code))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names: List[str] = []
            for target in node.targets:
                names.extend(extract_target_names(target))
            return names
        elif isinstance(node, ast.AugAssign):
            names: List[str] = []
            for target in [node.target]:
                names.extend(extract_target_names(target))
            return names
        elif isinstance(node, ast.AnnAssign):
            names: List[str] = []
            for target in [node.target]:
                names.extend(extract_target_names(target))
            return names
    return []
def set_return_annotation(
    node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
    annotation_str: str
) -> None:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise TypeError(f"Expected FunctionDef or AsyncFunctionDef, got {type(node).__name__}")

    expr_ast = ast.parse(split_unpack_in_code(annotation_str), mode='eval').body  # type: ignore

    node.returns = expr_ast

def load_project_data(repo_name:str):
    exit_code = os.system("python run_read_data.py {}".format(repo_name))

    if exit_code == 0:
        logger.debug("load repo data success")
    else:
        logger.error(f"load repo data fail ：{exit_code} repo: {repo_name}")

def save_projects_to_json(projects: List[OutPutData], filename: str) -> None:

    projects_dict = [p._asdict() for p in projects]

    existing_data = []
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        except json.JSONDecodeError:
            existing_data = []
        except Exception as e:
            print(f"error ({e})")
            existing_data = []

    all_data = existing_data + projects_dict

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, indent=4, ensure_ascii=False)

def load_json_data(file_path: str) -> JsonData:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"error: {e}")
        return []
    
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

def is_within_function(
    node: ast.AST,
    func_name: str
) -> bool:
    cur = node
    while hasattr(cur, 'parent'):
        parent = getattr(cur, 'parent')
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)) and parent.name == func_name:
            return True
        cur = parent
    return False
def add_parent_links(node: ast.AST, parent: ast.AST = None) -> None:
    for child in ast.iter_child_nodes(node):
        setattr(child, 'parent', node)
        add_parent_links(child, child)
def add_output_data2(src_json, slicing, other_prompt, generations, total_prompt = ""):
    cat = src_json.get('cat')
    file = src_json.get('file')
    generic = src_json.get('generic')
    gttype = src_json.get('gttype')
    name = src_json.get('name')
    origttype = src_json.get('origttype')
    processed_gttype = src_json.get('processed_gttype')
    scope = src_json.get('scope')
    type_depth = src_json.get('type_depth')
    loc = src_json.get('loc')

    temp_data = OutPutData(cat = cat, file = file, generic = generic, gttype= gttype, name = name, origttype= origttype, processed_gttype=processed_gttype,
                           scope=scope, type_depth=type_depth, loc=loc, code_slicing=slicing, other_prompt=other_prompt, prediction=generations, total_prompt=total_prompt)

    total_out_data.append(temp_data)
def collect_function_defs_from_dir(file_path: str) -> List[Tuple[str, ast.FunctionDef]]:
    func_defs: List[ast.FunctionDef] = []

    try:
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(split_unpack_in_code(source), filename=file_path)
    except (SyntaxError, UnicodeDecodeError):
        logger.warning(f"error:{file_path}")

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            func_defs.append(node)

    return func_defs, tree
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
        raise TypeError("error")

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

def find_variable_declarations(file_path: str) -> List[VarDeclNode]:
    with open(file_path, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(split_unpack_in_code(source), filename=file_path)

    decls: List[VarDeclNode] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            valid = True
            for t in node.targets:
                if not isinstance(t, (ast.Name, ast.Tuple, ast.List, ast.Attribute)):
                    valid = False
            if valid:
                decls.append(node)

        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                decls.append(node)

    return decls, tree


if __name__ == "__main__":
    data = load_json_data(dataset_path)
    if not data:
        logger.error("error")
        exit()
    logger.debug("len data:{}".format(len(data)))
    first = data[0]
    
    GPT_client: GPT_Client = GPT_Client(api_key)
    log_file_path = "./logs/a.log"
    error_count = 0
    write_count = 0
    total_count = 0
    last_repo_name = ""
    c1, c2, c3 = 0, 0, 0
    start_time1  = time.time()
    for idx, entry in enumerate(data):
        file_path = "./"+entry.get('file')
        target_name = entry.get("name")
        right_type = entry.get("processed_gttype")
        data_type = entry.get("scope")
        data_cat = entry.get("cat")
        old_ans = entry.get("prediction")[0]
        is_ud = False
        if data_cat == "user-defined":
            is_ud = True
        local_f = entry.get("loc").split("@")[0]
        is_get_node = False
        repo_name = file_path.replace("./repos/","").split("/")[0]
        write_count += 1
        if write_count % 500 == 0:
            save_projects_to_json(total_out_data, output_fs_path + str(write_count) + "_times_us" + "_out.json")
            logger.debug(f"test count:{write_count}")

        if repo_name != last_repo_name:
            load_project_data("./repos/"+repo_name)
            last_repo_name = repo_name
            start_time2 = time.time()

        slicer = Slicer(file_path)
        if data_type == "arg":
            c1+=1
            ans3, root3 = extract_function_params(file_path)
            for i in ans3.keys():
                if i.name != local_f:
                    continue
                for j in range(len(ans3[i])):
                    if ans3[i][j] != target_name:
                        continue
                    set_param_annotation(i, ans3[i][j], "mask")
                    total_count+=1
                    res = slicer.slicing_params(i, root3, ans3[i][j], file_path).replace("mask","<mask>")
                    other_prompts = slicer.get_other_prompt()
                    ans = GPT_client.Generate_Type_Hint2(res,slicer.get_type_recommend(),other_prompts,1)
                    total_prompt =GPT_Client.get_total_prompt()
                    add_output_data2(entry, res, other_prompts, ans,total_prompt=total_prompt)
                    break

        elif data_type == "return":
            c2+=1
            ans2, root2 = collect_function_defs_from_dir(file_path)
            for i in ans2:
                if i.name != target_name:
                    continue
                set_return_annotation(i, "mask")
                res = slicer.slicing_func(i, root2, file_path).replace("mask", "<mask>")
                other_prompts = slicer.get_other_prompt()
                strip_type_annotations(i)
                total_count+=1
                ans = GPT_client.Generate_Type_Hint2(res, [],other_prompts,1)
                total_prompt = GPT_Client.get_total_prompt()
                add_output_data2(entry, res, other_prompts, ans,total_prompt)
                break

        else:
            c3+=1
            total_count+=1
            var_defines, root1 = find_variable_declarations(file_path)
            for i in var_defines:
                # var_names = get_lhs(i)
                var_names = get_assign_targets(i)
                # if target_name not in var_names and "self."+target_name in var_names:
                #     target_name = "self."+target_name
                if target_name not in var_names:
                    continue
                add_parent_links(root1)
                if local_f!="global" and not is_within_function(i, local_f):
                    continue
                is_get_node = True
                fix_type_line = modify_annotation(i, '<mask>')
                src_line = ast.unparse(i)
                sliced_data = slicer.slicing_var(i, root1, file_path)
                other_prompts = slicer.get_other_prompt()
                if src_line not in sliced_data:
                    if src_line.replace("'",'"') in sliced_data:
                        sliced_data = sliced_data.replace(src_line.replace("'",'"'), fix_type_line)
                    elif src_line.replace('"',"'") in sliced_data:
                        sliced_data = sliced_data.replace(src_line.replace('"',"'"), fix_type_line)
                    else:
                        sliced_data =sliced_data.replace("\n"+target_name+" = ","\n"+target_name+": <mask> = ")
                ans = GPT_client.Generate_Type_Hint2(sliced_data.replace(src_line, fix_type_line), slicer.get_type_recommend(), other_prompts,1)
                total_prompt = GPT_Client.get_total_prompt()
                add_output_data2(entry, sliced_data.replace(src_line, fix_type_line), other_prompts, ans, total_prompt)
                break
        if not is_get_node:
            logger.debug(f"not found data:{entry}")

    if len(total_out_data)>0:
        save_projects_to_json(total_out_data, output_fs_path+"out.json")