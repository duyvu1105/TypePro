import json
from typing import List, Dict, Union, Any, Optional
import re
import random
from tool import wrap_with_union,convert_type_annotation, split_unpack_in_code, attribute_to_string
from type_defined import OutPutData
from hityper.typeobject import TypeObject

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

VarDeclNode = Union[ast.Assign, ast.AnnAssign]

def _lineno_col_to_index(source: str, lineno: int, col: int) -> int:
    if lineno < 1:
        raise ValueError("lineno must be >= 1")
    lines = source.splitlines(keepends=True)
    if lineno > len(lines):
        return len(source)
    return sum(len(lines[i]) for i in range(lineno - 1)) + col

def surrounding_text(node: ast.AST, source: str, before: int = 150, after: int = 150) -> Dict[str, Any]:
    if not hasattr(node, "lineno") or not hasattr(node, "col_offset"):
        raise ValueError("(lineno / col_offset)。")

    start = _lineno_col_to_index(source, node.lineno, node.col_offset)

    end = None
    if getattr(node, "end_lineno", None) is not None and getattr(node, "end_col_offset", None) is not None:
        end = _lineno_col_to_index(source, node.end_lineno, node.end_col_offset)
    else:
        try:
            seg = ast.get_source_segment(source, node)
            if seg is not None:
                end = start + len(seg)
        except Exception:
            seg = None
        if end is None:
            lines = source.splitlines(keepends=True)
            if 1 <= node.lineno <= len(lines):
                end = sum(len(lines[i]) for i in range(node.lineno))  
            else:
                end = start

    before_start = max(0, start - before)
    after_end = min(len(source), end + after)

    return {
        "before": source[before_start:start],
        "node": source[start:end],
        "after": source[end:after_end],
        "start_index": start,
        "end_index": end,
        "before_start": before_start,
        "after_end": after_end,
    }

def find_variable_declarations(file_path: str):
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

    return decls, tree, source

def judge_right(predictions_list, references)->bool:
    pred = predictions_list[0]
    gt_type_obj = TypeObject.Str2Obj(references.strip())
    pre_type_obj = TypeObject.Str2Obj(pred.strip())
    if TypeObject.isIdenticalSet(gt_type_obj, pre_type_obj):
        return True
    return False

def surrounding_substrings(
    A: str,
    B: str,
    radius: int = 200,
    case_sensitive: bool = True,
    max_matches: Optional[int] = None
) -> List[Dict]:
    if B is None or B == "":
        raise ValueError("B empty")

    flags = 0 if case_sensitive else re.IGNORECASE

    pattern = re.compile(r'(?=({}))'.format(re.escape(B)), flags)

    results: List[Dict] = []
    for m in pattern.finditer(A):

        matched = m.group(1)
        start = m.start()
        end = start + len(matched)

        s = max(0, start - radius)
        e = min(len(A), end + radius)
        snippet = A[s:e]
        left = A[s:start]
        right = A[end:e]
        rel_start = len(left)

        results.append({
            "match_text": matched,
            "start": start,
            "end": end,
            "snippet": snippet,
            "left": left,
            "right": right,
            "snippet_rel_start": rel_start,
        })

        if max_matches is not None and len(results) >= max_matches:
            break

    return results

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

def find_param_node(func_node: ast.AST, name: str) -> Optional[Tuple[ast.arg, str]]:
 
    if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        raise TypeError("func_node must be FunctionDef / AsyncFunctionDef / Lambda ast Node")

    args = func_node.args  # type: ignore[attr-defined]

    for a in getattr(args, "posonlyargs", []):
        if a.arg == name:
            return a, "posonly"

    for a in getattr(args, "args", []):
        if a.arg == name:
            return a, "positional"

    # *args
    vararg = getattr(args, "vararg", None)
    if vararg is not None and getattr(vararg, "arg", None) == name:
        return vararg, "vararg"

    # keyword-only args
    for a in getattr(args, "kwonlyargs", []):
        if a.arg == name:
            return a, "kwonly"

    # **kwargs
    kwarg = getattr(args, "kwarg", None)
    if kwarg is not None and getattr(kwarg, "arg", None) == name:
        return kwarg, "kwarg"

    return None

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


def set_param_annotation(
    node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
    param_name: str,
    annotation_str: str
) -> None:
   
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise TypeError(f"Expected FunctionDef or AsyncFunctionDef, got {type(node).__name__}")

    ann_expr = ast.parse(split_unpack_in_code(annotation_str), mode='eval').body  # type: ignore

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
        tree = ast.parse(split_unpack_in_code(source), filename=file_path)
    except (SyntaxError, UnicodeDecodeError):
       
        logger.warning(f"parse filed:{file_path}")

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            func_defs.append(node)

    return func_defs, tree

def extract_function_params(file_path: str) -> Dict[ast.FunctionDef, List[str]]:
    with open(file_path, encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(split_unpack_in_code(source), filename=file_path)
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
        raise TypeError("")


    ast.fix_missing_locations(new_node)

    mod = ast.Module(body=[new_node], type_ignores=[])
    ast.fix_missing_locations(mod)
    return ast.unparse(mod.body[0])

def add_parent_links(node: ast.AST, parent: ast.AST = None) -> None:

    for child in ast.iter_child_nodes(node):
        setattr(child, 'parent', node)
        add_parent_links(child, child)


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

def load_json_data(file_path: str) -> JsonData:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"error: {e}")
        return []

def get_lhs(node: ast.AST) -> List[str]:

    lhs_nodes = []
    if isinstance(node, ast.Assign):
        
        lhs_nodes = node.targets
    elif isinstance(node, ast.AugAssign):
        
        lhs_nodes = [node.target]
    elif isinstance(node, ast.AnnAssign):
       
        lhs_nodes = [node.target]
    else:
        return []
    results = []
    for target in lhs_nodes:
        try:
            results.append(ast.unparse(target).strip())
        except AttributeError:
            
            if isinstance(target, ast.Name):
                results.append(target.id)
            elif isinstance(target, ast.Attribute):
                # obj.attr
                val = ast.unparse(target.value) if hasattr(ast, "unparse") else ""
                results.append(f"{val}.{target.attr}")
            else:
                results.append(repr(target))
    return results

def smart_replace(source: str, old: str, new: str) -> str:

    if not source or not old:
        return source

    escaped_old = re.escape(old)
   
    pattern = rf"""(['"])({escaped_old})\1"""

    def replacer(match):
        quote_char = match.group(1)  
        return f"{quote_char}{new}{quote_char}" 

    return re.sub(pattern, replacer, source)

def load_project_data(repo_name:str):

    exit_code = os.system("python run_read_data.py {}".format(repo_name))

    if exit_code == 0:
        logger.debug("load repo data success")
    else:
        logger.error(f"load repo data fail {exit_code} repo: {repo_name}")

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
            print(f"error: {e}")
            existing_data = []

    all_data = existing_data + projects_dict

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, indent=4, ensure_ascii=False)

def add_output_data(src_json, slicing, other_prompt, generation, total_prompt = ""):
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
                           scope=scope, type_depth=type_depth, loc=loc, code_slicing=slicing, other_prompt=other_prompt, prediction=[generation], total_prompt=total_prompt)

    total_out_data.append(temp_data)


def generation_test_code(ans, limit_length:int = 200):
     node = ans["node"].replace("mask", "<mask>")
     before = ans["before"]
     after = ans['after']
     if len(node)>limit_length*2:
         return node[:limit_length*2]
     elif len(node)+len(before) > limit_length*2:
         new_str = before+node
         return new_str[:limit_length*2]
     else:
         new_str = before + node + after
         return new_str[:limit_length*2]

if __name__ == "__main__":
   pass