import ast
from loguru import logger
from type_defined import ProjectDefined, ProjectUseData, stmt_types, FunctionInfo, OTHER_PROMPTS,SIMPLE_BINOPS
from function_methods import Function_methods
from typing import List, Optional, Union, Dict,Iterable,Type
from import_analyzer import importAnalyzer
from tool import split_unpack_in_code
ScopeNode = Union[ast.FunctionDef, ast.ClassDef, ast.Module]

FILE_PATH = ""
file_lines = []
func_sig_list = []

class Slicer:

    maybe_class = False
    def __init__(self, file_name:str):
        self.file_name = file_name
        self.Funcion_methods = Function_methods()
        self.import_analyzer = importAnalyzer(file_name)
        self.other_prompts = []
        self.type_recommend = []

    def add_type_recommendations(self, definitions: Iterable[str], prepend: bool = False):
        values = [definition for definition in definitions if definition]
        if prepend:
            for definition in reversed(values):
                if definition in self.type_recommend:
                    self.type_recommend.remove(definition)
                self.type_recommend.insert(0, definition)
            return
        for definition in values:
            if definition not in self.type_recommend:
                self.type_recommend.append(definition)

    def is_simple_op_assign(self,node: ast.AST,
                            ops: Iterable[Type[ast.operator]] = SIMPLE_BINOPS
                            ) -> bool:
        if not isinstance(node, ast.Assign):
            return False

        val = node.value
        return (
                isinstance(val, ast.BinOp)
                and any(isinstance(val.op, op) for op in ops)
        )

    def get_import_info(self,file_path: str, source: str = None):

        if source == None:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()
                source = split_unpack_in_code(source)

        tree = ast.parse(source)
        import_infos = [node for node in ast.walk(tree) if
                        isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom)]

        return import_infos

    def add_func_defined(self,fun_sig: str):
        global func_sig_list
        func_sig_list.append(fun_sig)

    def get_assign_var(self,node: ast.AST, file_path: str, target_name: str, Domain: (ast.AST, str) = None):
        total_ans = []
        func_sig_list = []
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        if target_name not in self.get_lhs(node) and not self.is_simple_op_assign(node):  
            data = self.get_lhs(node)
        else:
            data = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
        for n in data:
            if n != target_name:
                ans, temp_sig_list = self.find_statements_for_var(file_path, n, False, Domain)
                for f in temp_sig_list:
                    func_sig_list.append(f)
                total_ans.extend(ans)
        sorted_data = sorted(total_ans, key=lambda x: x[1])
        return sorted_data, func_sig_list

    def is_call_stmt(self,node: ast.stmt) -> bool:
        if isinstance(node, ast.Assign):
            return isinstance(node.value, ast.Call)
        elif isinstance(node, ast.AnnAssign):
            return isinstance(node.value, ast.Call)
        elif isinstance(node, ast.Expr):
            return isinstance(node.value, ast.Call)
        elif isinstance(node, ast.Return):
            return isinstance(node.value, ast.Call)
        return False

    def is_assignment(self,node: ast.AST) -> bool:

        return isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign))

    def get_signature_line(self,node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> str:

        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            raise TypeError(f"Expected FunctionDef or AsyncFunctionDef, got {type(node).__name__}")


        prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "

        def format_arg(arg: ast.arg, default: ast.expr = None):
            name = arg.arg
            ann = f": {ast.unparse(arg.annotation)}" if arg.annotation is not None else ""
            df = f"={ast.unparse(default)}" if default is not None else ""
            return f"{name}{ann}{df}"

        parts = []
        args = node.args.args
        defaults = node.args.defaults or []
        n_args = len(args)
        n_def = len(defaults)
        for i, arg in enumerate(args):
            default = defaults[i - (n_args - n_def)] if i >= n_args - n_def else None
            parts.append(format_arg(arg, default))

        # vararg: *args
        if node.args.vararg:
            parts.append(f"*{format_arg(node.args.vararg)}")

        # keyword-only
        for arg, default in zip(node.args.kwonlyargs,
                                node.args.kw_defaults or []):
            parts.append(format_arg(arg, default))

        # kwarg: **kwargs
        if node.args.kwarg:
            parts.append(f"**{format_arg(node.args.kwarg)}")

        args_str = ", ".join(parts)

        ret = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""

        return f"{prefix}{node.name}({args_str}){ret}:"

    def get_call_func_names(self,node: ast.Call) -> list:
        names = []
        func = node.func
        while isinstance(func, ast.Attribute):
            names.insert(0, func.attr)
            func = func.value
        if isinstance(func, ast.Name):
            names.insert(0, func.id)

        target_name = ".".join(names)
        fun_sig = self.Funcion_methods.get_target_name_signals(target_name)
        cls_sigs = self.Funcion_methods.get_class_by_names(target_name)
        if len(cls_sigs)>0:
            for c in cls_sigs:
                fun_sig.append(c)

        if len(fun_sig) == 0:
            tpf = self.import_analyzer.get_function_by_name(target_name)
            for i in tpf:
                if type(i) == FunctionInfo:
                    fun_sig.append(i.signature)
        return fun_sig

    def get_lhs(self,node: ast.AST) -> List[str]:
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

    def get_assign_targets(self,assign_node: ast.Assign) -> List[str]:

        names = []
        for target in assign_node.targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
            elif isinstance(target, (ast.Tuple, ast.List)):
                for elt in target.elts:
                    if isinstance(elt, ast.Name):
                        names.append(elt.id)
        return names

    # 在文件中找到目标变量的名称的语句行
    def find_statements_for_var(self,file_path: str, var_name: str, is_for_defined: bool = True,
                                Domain: (ast.AST, str) = None):

        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
            source = split_unpack_in_code(source)
        if Domain == None:
            tree = ast.parse(source, filename=file_path)
        else:
            tree = Domain[0]
            source = Domain[1]

        results = [] 
        func_sig_t = []
        for node in ast.walk(tree):
            if isinstance(node, stmt_types) and hasattr(node, 'lineno'):
                for child in ast.walk(node):
                    if isinstance(child, ast.Name) and child.id == var_name:

                        if self.is_call_stmt(node):
                            call_node = node.value  # ast.Call
                            func_sigs = self.get_call_func_names(call_node)
                            for f in func_sigs:
                                if f not in func_sig_t:
                                    func_sig_t.append(f)

                        if isinstance(node, ast.Assign) and is_for_defined:

                            other_data, temp_sig_list = self.get_assign_var(node, file_path, var_name, Domain)
                            for d in other_data:
                                results.append(d)
                            for f in temp_sig_list:
                                if f not in func_sig_t:
                                    func_sig_t.append(f)
                        lineno = node.lineno
                        # code_line = lines[lineno - 1].strip()
                        code_line = ast.unparse(node)
                        results.append((code_line, lineno))
                        break

        seen = set()
        res = []
        for code_line, lineno in sorted(results, key=lambda x: x[1]):
            if lineno not in seen:
                res.append((code_line, lineno))
                seen.add(lineno)
        return res, func_sig_t

    def get_name_fun_node(self, file_path: str, func_name: str):

        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()

        source = split_unpack_in_code(source)
        tree = ast.parse(source, filename=file_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                return node, tree
        return None, tree

    def is_descendant(self,ancestor: ast.AST, child: ast.AST) -> bool:
        for node in ast.walk(ancestor):
            if node is child:
                return True
        return False

    def annotate_parents(self,tree: ast.AST) -> None:

        for parent in ast.walk(tree):
            for field, value in ast.iter_fields(parent):
                if isinstance(value, ast.AST):
                    value._parent = parent
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, ast.AST):
                            item._parent = parent

    def find_statements_with_var(self,file_path: str, var_name: str) -> List[ast.stmt]:

        with open(file_path, encoding="utf-8") as f:
            source = f.read()

        source = split_unpack_in_code(source)
        tree = ast.parse(source, filename=file_path)
        self.annotate_parents(tree)

        stmts = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == var_name:
                parent = node
                while parent and not isinstance(parent, ast.stmt):
                    parent = getattr(parent, "_parent", None)
                if parent:
                    stmts.add(parent)

        return list(stmts)

    def get_nodes_spanning_line(self,tree: ast.AST, target_lineno: int) -> List[ast.AST]:

        matches = []
        for node in ast.walk(tree):
            if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
                if node.lineno <= target_lineno <= node.end_lineno:
                    matches.append(node)
        return matches

    def build_parent_map(self,tree):
        parent_map = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parent_map[child] = node
        return parent_map

    def get_scope_node(self,root, node):
        parent_map = self.build_parent_map(root)
        current = node

        while current is not None:
            if isinstance(current, (ast.Module, ast.FunctionDef,
                                    ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                return current
            current = parent_map.get(current)
        return root

    def extract_base_names(self,node: ast.AST) -> List[str]:

        if isinstance(node, ast.Name):
            return [node.id]
        elif isinstance(node, ast.Attribute):
            try:
                return [ast.unparse(node)]
            except AttributeError:
                parts = []
                cur = node
                while isinstance(cur, ast.Attribute):
                    parts.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    parts.append(cur.id)
                return [".".join(reversed(parts))]
        elif isinstance(node, ast.Subscript):
            return self.extract_base_names(node.value)
        else:
            return []

    def get_name_args_from_call(self,call_node: ast.Call) -> List[str]:
        names: List[str] = []
        if isinstance(call_node, ast.Expr):
            call_node = call_node.value
        for arg in call_node.args:
            names.extend(self.extract_base_names(arg))
        for kw in call_node.keywords:
            names.extend(self.extract_base_names(kw.value))
        return names

    def parse_use_data(self,data: ProjectUseData):

        fix_srcCode  = split_unpack_in_code(data.source_code)
        param_all_data = [fix_srcCode]
        func_sig_used_list = []
        try:
            call_node = ast.parse(fix_srcCode)
            for i in ast.walk(call_node):
                if isinstance(i, ast.Call):
                    params_list = self.get_name_args_from_call(i)
                    for p_identify in params_list:
                        identify_slicing, sigs = self.find_statements_for_var(data.file_name, p_identify, False)
                        for s in identify_slicing:
                            if s[0] not in param_all_data:
                                param_all_data.append(s[0])
                        for f in sigs:
                            func_sig_used_list.append(f)
                    break
        except:
            logger.warning(f"analysizer use data error {data.name}, code:{fix_srcCode}")

        return param_all_data, func_sig_used_list

    def find_variable_nodes(self,file_path: str, var_name: str) -> List[ast.Name]:
        
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        source = split_unpack_in_code(source)
        tree = ast.parse(source, filename=file_path)

        matches: List[ast.Name] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == var_name:
                matches.append(node)
        return matches

    def collect_func_slicing(self,node: Union[ast.FunctionDef, ast.AsyncFunctionDef], file_path: str):

        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()

        function_name = node.name
        source = split_unpack_in_code(source)
        tree = ast.parse(source, filename=file_path)
        res = []
        call_node_str = []
        func_return_data = []
        for node1 in ast.walk(node):
            if isinstance(node1, ast.Call):
                if isinstance(node1.func, ast.Name):
                    name = node1.func.id
                elif isinstance(node1.func, ast.Attribute):
                    name = node1.func.attr
                else:
                    continue

                func_sigs = self.get_call_func_names(node1)
                for i in func_sigs:
                    if i not in call_node_str:
                        call_node_str.append(i)

            elif isinstance(node, ast.Return):
                ret_expr = ast.get_source_segment(source, node.value) if node.value else ""
                for node2 in ast.walk(node):
                    if isinstance(node2, ast.Name):
                        datas = self.find_statements_with_var(file_path, node2.id)
                        for d in datas:
                            if not self.is_descendant(node, d) and self.is_assignment(d):
                                lhs = self.get_lhs(d)
                                if node2.id in lhs:
                                    func_return_data.append(ast.get_source_segment(source, d))

        other_Use = self.Funcion_methods.get_function_use_data(function_name)
        total_use_data = []
        for u in other_Use:
            data, sig = self.parse_use_data(u)
            for s in sig:
                if s not in call_node_str and s not in func_sig_list and "def " + function_name not in s:
                    total_use_data.append(s)
            for d in data:
                if d not in total_use_data:
                    total_use_data.append(d)

        function_code = ast.unparse(node)

        total_code = ""
        total_code_list = []
        for f in call_node_str:
            if f not in total_code_list:
                total_code_list.append(f)
        for i in func_return_data:
            if i not in total_code_list:
                total_code_list.append(i)
        total_code_list.append(function_code)
        for p in total_use_data:
            if p not in total_code_list:
                total_code_list.append(p)

        total_code = "\n".join(total_code_list)

        return total_code

    def find_var_node(self,file_name: str, target_code_line: str):
        with open(file_name, 'r', encoding='utf-8') as f:
            source = f.read()
        source = split_unpack_in_code(source)
        tree = ast.parse(source, filename=file_name)
        nodes = [node for node in ast.walk(tree) if
                 isinstance(node, ast.Assign) or isinstance(node, ast.AugAssign) or isinstance(node, ast.AnnAssign)]
        for node in nodes:
            if ast.get_source_segment(source, node) == target_code_line:
                return node, tree

        return None, tree

    def get_function_params_node(self,func_node: ast.FunctionDef, params_name: str):
        params: List[ast.arg] = []

        params.extend(func_node.args.posonlyargs)

        params.extend(func_node.args.args)

        if func_node.args.vararg:
            params.append(func_node.args.vararg)

        params.extend(func_node.args.kwonlyargs)

        if func_node.args.kwarg:
            params.append(func_node.args.kwarg)

        for i in params:
            if i.arg == params_name:
                return i
        return None

    def build_parent_map(self,tree):
        parent_map = {}
        stack = [tree]
        while stack:
            current_node = stack.pop()
            for child in ast.iter_child_nodes(current_node):
                parent_map[child] = current_node
                stack.append(child)
        return parent_map

    def find_class_and_field_usage(self,file_path, function_name, field_name):
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()

        tree = ast.parse(source)
        parent_map = self.build_parent_map(tree)

        target_function = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
                target_function = node
                break

        if not target_function:
            return None, []

        class_node = None
        current = target_function
        while current in parent_map:
            current = parent_map[current]
            if isinstance(current, ast.ClassDef):
                class_node = current
                break

        if not class_node:
            return None, []

        field_usage_nodes = []

        class FieldUsageVisitor(ast.NodeVisitor):
            def visit_Attribute(self, node):
                if (isinstance(node.value, ast.Name) and
                        node.value.id == 'self' and
                        node.attr == field_name):
                    stmt_node = node
                    while not isinstance(stmt_node, (ast.stmt)) and stmt_node in parent_map:
                        stmt_node = parent_map[stmt_node]
                    if isinstance(stmt_node, ast.stmt):
                        field_usage_nodes.append(stmt_node)
                self.generic_visit(node)

        visitor = FieldUsageVisitor()
        for node in class_node.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visitor.visit(node)

        return class_node, field_usage_nodes

    def slicing_var(self,var_node: ast.AST, root: ast.AST, file_path: str):
        target_var_name = self.get_lhs(var_node)[0]
        if type(var_node) == ast.Assign:
            init_interface = self.infer_assign_target_types(var_node)

            if target_var_name in init_interface:
                if init_interface[target_var_name] != "Any":
                    self.other_prompts.append(OTHER_PROMPTS["init_type"].format(init_interface[target_var_name]))
        if self.maybe_class:
            self.other_prompts.append(OTHER_PROMPTS["class"])
        total_code_list = []
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        if var_node != None:
            root1 = self.get_scope_node(root, var_node)

        may_cls_data = self.Funcion_methods.find_file_class_name(file_path, target_var_name)
        may_cls_data2 = self.Funcion_methods.calculate_similarity_for_class_name(target_var_name)
        if may_cls_data!="":
            total_code_list.append(may_cls_data)
        if len(may_cls_data)>0:
            self.add_type_recommendations(may_cls_data2)
        self.add_type_recommendations(
            self.import_analyzer.get_class_recommendations(target_var_name)
        )
        res, sigs = self.find_statements_for_var(file_path, target_var_name, is_for_defined=True,
                                            Domain=(root1, source))

        total_code = ""
        import_infos = self.get_import_info(file_path, source)
        for i_f in import_infos:
            if ast.get_source_segment(source, i_f) not in total_code_list:
                total_code_list.append(ast.get_source_segment(source, i_f))
        for fs in sigs:
            if fs not in total_code_list:
                total_code_list.append(fs)
        for i in res:
            if i[0] not in total_code_list:
                total_code_list.append(i[0])
        total_code = "\n".join(total_code_list)
        self.add_type_recommendations(
            self.import_analyzer.calculate_similarity_for_class(total_code), prepend=True
        )
        return total_code

    def slicing_func(self,func_node: ast.AST, root: str, file_path: str):
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        if func_node:
            total_code = ""
            import_infos = self.get_import_info(file_path, source)
            for i_f in import_infos:
                total_code = total_code + ast.get_source_segment(source, i_f) + "\n"

            func_slicing = self.collect_func_slicing(func_node, file_path)
            total_code = total_code + func_slicing

            func_sig_list.clear()
            return total_code

        return ""

    def slicing_params(self,func_node: ast.AST, root: ast.AST, param_name: str, file_path: str):
        total_code_list = []

        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()

        if func_node:
            func_name = func_node.name
            total_code = ""
            import_infos = self.get_import_info(file_path, source)
            for i_f in import_infos:
                if ast.get_source_segment(source, i_f) not in total_code_list:
                    total_code_list.append(ast.get_source_segment(source, i_f))

            # params_node = get_function_params_node(func_node, param_name)
            lines = source.splitlines()
            params_line = self.get_signature_line(func_node)
            may_class = self.Funcion_methods.find_file_class_name(file_path, param_name)
            may_class_2 = self.Funcion_methods.calculate_similarity_for_class_name(param_name)
            if may_class!="":
                total_code_list.append(may_class)
            if len(may_class_2)>0:
                self.add_type_recommendations(may_class_2)
            self.add_type_recommendations(
                self.import_analyzer.get_class_recommendations(param_name)
            )

            res, sigs = self.find_statements_for_var(file_path, param_name, is_for_defined=True, Domain=(func_node, ast.unparse(func_node)))
            for fs in sigs:
                if fs not in total_code_list:
                    total_code_list.append(fs)
            total_code_list.append(ast.unparse(func_node))

            other_Use = self.Funcion_methods.get_function_use_data(func_name)
            total_use_data = []
            for u in other_Use:
                data, sigs2 = self.parse_use_data(u)
                for s in sigs2:
                    if s not in sigs and "def " + func_name not in s:
                        total_use_data.append(s)
                for d in data:
                    if d not in total_use_data:
                        total_use_data.append(d)
            for fu in total_use_data:
                if fu not in total_code_list:
                    total_code_list.append(fu)

            total_code = "\n".join(total_code_list)
            self.add_type_recommendations(
                self.import_analyzer.calculate_similarity_for_class(total_code), prepend=True
            )
            return total_code

    def get_type_recommend(self):
        return self.type_recommend

    def load_data(self):
        pass

    def get_other_prompt(self):
        return self.other_prompts

    def infer_expr_type(self,expr: ast.expr) -> str:

        if isinstance(expr, ast.Constant):
            py_val = expr.value
            return type(py_val).__name__

        if isinstance(expr, ast.List):
            return "List"
        if isinstance(expr, ast.Tuple):
            return "Tuple"
        if isinstance(expr, ast.Set):
            return "Set"
        if isinstance(expr, ast.Dict):
            return "Dict"

        if isinstance(expr, ast.Call):
            func = expr.func
            if isinstance(func, ast.Name):
                cls_sigs = self.Funcion_methods.get_class_by_names(func.id)
                if len(cls_sigs) > 0:
                    self.maybe_class = True
                    return "class {}".format(func.id)
                else:
                    return "The return value of {} or class {}".format(func.id, func.id)
        if isinstance(expr, ast.BinOp):
            return self.infer_expr_type(expr.left)

        return "Any"

    def infer_assign_target_types(self,
            assign_node: ast.Assign
    ) -> Dict[str, str]:
        if not isinstance(assign_node, ast.Assign):
            raise TypeError(f"Expected ast.Assign, got {type(assign_node).__name__}")

        value = assign_node.value
        inferred = {}

        for target in assign_node.targets:
            if isinstance(target, ast.Name):
                name = target.id
            elif isinstance(target, ast.Attribute):
                name = target.attr
            else:
                continue

            inferred[name] = self.infer_expr_type(value)

        return inferred

def test_var():

    var_slicer = Slicer(FILE_PATH)
    with open(FILE_PATH, 'r', encoding='utf-8') as f:
        source = f.read()
    target_var = "CONF_INTERRUPT = 'interrupt'"
    data, root = var_slicer.find_var_node(FILE_PATH, target_var)
    ans = var_slicer.slicing_var(data, root, FILE_PATH)
    other_prompt = var_slicer.get_other_prompt()
    logger.debug(other_prompt)
    logger.info(ans)

def test_fun():
    pass


def test_params():
    pass

def main():
    pass


if __name__ == '__main__':
    main()
