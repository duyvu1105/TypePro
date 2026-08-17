import ast
import re
from collections import OrderedDict, defaultdict
from loguru import logger
from type_defined import ProjectDefined, ProjectUseData, stmt_types, FunctionInfo, OTHER_PROMPTS,SIMPLE_BINOPS
from function_methods import Function_methods
from typing import List, Optional, Union, Dict, Iterable, Type, NamedTuple
from import_analyzer import importAnalyzer
from tool import split_unpack_in_code
from type_signal_analyzer import visible_type_signals
ScopeNode = Union[ast.FunctionDef, ast.ClassDef, ast.Module]

FILE_PATH = ""
file_lines = []
func_sig_list = []


class CachedStatement(NamedTuple):
    """Compact statement data; deliberately holds no AST references."""

    code_line: str
    lineno: int
    call_target: str | None
    is_assign: bool
    lhs: tuple[str, ...]
    names: tuple[str, ...]
    simple_op_assign: bool


def _call_target_name(node: ast.Call) -> str:
    names = []
    func = node.func
    while isinstance(func, ast.Attribute):
        names.insert(0, func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        names.insert(0, func.id)
    return ".".join(names)


def _lhs(node: ast.AST) -> list[str]:
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
                value = ast.unparse(target.value) if hasattr(ast, "unparse") else ""
                results.append(f"{value}.{target.attr}")
            else:
                results.append(repr(target))
    return results


def _is_call_statement(node: ast.stmt) -> bool:
    if isinstance(node, ast.Assign):
        return isinstance(node.value, ast.Call)
    if isinstance(node, ast.AnnAssign):
        return isinstance(node.value, ast.Call)
    if isinstance(node, ast.Expr):
        return isinstance(node.value, ast.Call)
    if isinstance(node, ast.Return):
        return isinstance(node.value, ast.Call)
    return False


def _is_simple_op_assignment(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Assign)
        and isinstance(node.value, ast.BinOp)
        and any(isinstance(node.value.op, op) for op in SIMPLE_BINOPS)
    )


def _append_unique(values: list, seen: set, value) -> bool:
    if value in seen:
        return False
    seen.add(value)
    values.append(value)
    return True


def class_definitions_from_text(source: str) -> list[str]:
    """Extract visible class/type declarations without consulting the label."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        tree = None
    if tree is not None:
        definitions = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [ast.unparse(value) for value in node.bases]
            header = (
                f"class {node.name}({', '.join(bases)}):"
                if bases else f"class {node.name}:"
            )
            lines = [header, "    # source: project", "    # kind: visible_class"]
            for statement in node.body[:40]:
                if isinstance(statement, ast.AnnAssign):
                    lines.append(
                        f"    {ast.unparse(statement.target)}: "
                        f"{ast.unparse(statement.annotation)}"
                    )
                elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    prefix = "async def" if isinstance(statement, ast.AsyncFunctionDef) else "def"
                    returns = (
                        f" -> {ast.unparse(statement.returns)}"
                        if statement.returns is not None else ""
                    )
                    lines.append(
                        f"    {prefix} {statement.name}({ast.unparse(statement.args)})"
                        f"{returns}: ..."
                    )
            if len(lines) == 3:
                lines.append("    pass")
            definitions.append("\n".join(lines))
        for node in tree.body:
            if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
                continue
            annotation = ast.unparse(node.annotation)
            if annotation.endswith("TypeAlias") and node.value is not None:
                definitions.append(
                    f"class {node.target.id}:\n"
                    "    # source: project\n"
                    "    # kind: alias\n"
                    f"    # type alias: {ast.unparse(node.value)}"
                )
        return list(dict.fromkeys(definitions))
    # Slices may concatenate independently valid snippets. Preserve class
    # headers as high-recall name candidates when the combined text is invalid.
    definitions = []
    for match in re.finditer(r"(?m)^\s*class\s+([A-Za-z_]\w*)\s*([^:]*):", source):
        definitions.append(
            f"class {match.group(1)}{match.group(2)}:\n"
            "    # source: project\n"
            "    # kind: visible_class\n"
            "    pass"
        )
    return list(dict.fromkeys(definitions))


class ProjectAnalysisCache:
    """Bounded, project-local caches for read-only source analysis."""

    def __init__(
        self,
        file_limit: int = 2048,
        statement_limit: int = 50000,
        use_limit: int = 100000,
        analyzer_limit: int = 256,
        function_limit: int = 4096,
    ):
        self.file_limit = file_limit
        self.statement_limit = statement_limit
        self.use_limit = use_limit
        self.analyzer_limit = analyzer_limit
        self.function_limit = function_limit
        self._structures = OrderedDict()
        self._statements = OrderedDict()
        self._uses = OrderedDict()
        self._analyzers = OrderedDict()
        self._function_uses = OrderedDict()
        self._function_outputs = OrderedDict()
        self.hits = defaultdict(int)
        self.misses = defaultdict(int)

    @staticmethod
    def _remember(cache: OrderedDict, key, value, limit: int):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > limit:
            cache.popitem(last=False)

    def file_analysis(self, file_path: str):
        cached = self._structures.get(file_path)
        if cached is not None:
            self._structures.move_to_end(file_path)
            self.hits["file"] += 1
            return cached
        self.misses["file"] += 1
        with open(file_path, "r", encoding="utf-8") as handle:
            source = split_unpack_in_code(handle.read())
        tree = ast.parse(source, filename=file_path)
        nodes_by_name = defaultdict(list)
        for node in ast.walk(tree):
            if not isinstance(node, stmt_types) or not hasattr(node, "lineno"):
                continue
            names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
            call_target = None
            if _is_call_statement(node):
                call_target = _call_target_name(node.value)
            statement = CachedStatement(
                code_line=ast.unparse(node),
                lineno=node.lineno,
                call_target=call_target,
                is_assign=isinstance(node, ast.Assign),
                lhs=tuple(_lhs(node)),
                names=tuple(names),
                simple_op_assign=_is_simple_op_assignment(node),
            )
            for name in names:
                nodes_by_name[name].append(statement)
        cached = {name: tuple(nodes) for name, nodes in nodes_by_name.items()}
        self._remember(self._structures, file_path, cached, self.file_limit)
        return cached

    def analyzer(self, file_path: str):
        cached = self._analyzers.get(file_path)
        if cached is not None:
            self._analyzers.move_to_end(file_path)
            self.hits["analyzer"] += 1
            return cached
        self.misses["analyzer"] += 1
        cached = importAnalyzer(file_path)
        self._remember(self._analyzers, file_path, cached, self.analyzer_limit)
        return cached

    def statement_result(self, key):
        cached = self._statements.get(key)
        if cached is None:
            self.misses["statement"] += 1
            return None
        self._statements.move_to_end(key)
        self.hits["statement"] += 1
        return list(cached[0]), list(cached[1])

    def remember_statement_result(self, key, results, signatures):
        self._remember(
            self._statements,
            key,
            (tuple(results), tuple(signatures)),
            self.statement_limit,
        )

    def use_result(self, key):
        cached = self._uses.get(key)
        if cached is None:
            self.misses["use"] += 1
            return None
        self._uses.move_to_end(key)
        self.hits["use"] += 1
        return list(cached[0]), list(cached[1])

    def remember_use_result(self, key, data, signatures):
        self._remember(
            self._uses,
            key,
            (tuple(data), tuple(signatures)),
            self.use_limit,
        )

    def function_use_events(self, key):
        cached = self._function_uses.get(key)
        if cached is None:
            self.misses["function"] += 1
            return None
        self._function_uses.move_to_end(key)
        self.hits["function"] += 1
        return cached

    def remember_function_use_events(self, key, events):
        self._remember(
            self._function_uses, key, tuple(events), self.function_limit
        )

    def function_output(self, key):
        cached = self._function_outputs.get(key)
        if cached is None:
            self.misses["function_output"] += 1
            return None
        self._function_outputs.move_to_end(key)
        self.hits["function_output"] += 1
        return list(cached)

    def remember_function_output(self, key, values):
        self._remember(
            self._function_outputs, key, tuple(values), self.function_limit
        )

    def summary(self) -> str:
        return " ".join(
            f"{name}_hits={self.hits[name]:,} {name}_misses={self.misses[name]:,}"
            for name in (
                "file", "statement", "use", "function", "function_output", "analyzer"
            )
        )

class Slicer:

    maybe_class = False
    def __init__(self, file_name:str, function_methods: Function_methods | None = None,
                 analysis_cache: ProjectAnalysisCache | None = None):
        self.file_name = file_name
        self.Funcion_methods = function_methods or Function_methods()
        self.analysis_cache = analysis_cache
        self.import_analyzer = (
            analysis_cache.analyzer(file_name)
            if analysis_cache is not None
            else importAnalyzer(file_name)
        )
        self._domain_statement_indexes = {}
        self.other_prompts = []
        self.type_recommend = []
        self._type_recommend_seen = set()

    def add_type_recommendations(self, definitions: Iterable[str], prepend: bool = False):
        values = [definition for definition in definitions if definition]
        if prepend:
            for definition in reversed(values):
                if definition in self._type_recommend_seen:
                    self.type_recommend.remove(definition)
                else:
                    self._type_recommend_seen.add(definition)
                self.type_recommend.insert(0, definition)
            return
        for definition in values:
            _append_unique(
                self.type_recommend, self._type_recommend_seen, definition
            )

    def add_high_recall_recommendations(
        self, target_name: str, source: str, file_path: str,
        function_name: str = "",
    ) -> None:
        """Union exact, project, lexical, and structural retrieval signals."""
        exact = [
            *self.import_analyzer.get_exact_import_recommendations(source),
            *class_definitions_from_text(source),
            *visible_type_signals(source),
            *self.Funcion_methods.exact_imported_class_definitions(file_path),
            *self.Funcion_methods.semantic_type_recommendations(
                file_path, target_name, function_name
            ),
            *self.import_analyzer.get_imported_module_inventory(target_name),
        ]
        fuzzy = [
            *self.Funcion_methods.calculate_similarity_for_class_name(target_name),
            *self.import_analyzer.get_class_recommendations(target_name),
            *self.import_analyzer.calculate_similarity_for_class(source),
        ]
        self.add_type_recommendations([*exact, *fuzzy], prepend=True)

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

    def get_cached_assign_var(
        self, statement: CachedStatement, file_path: str, target_name: str
    ):
        total_ans = []
        signatures = []
        if target_name not in statement.lhs and not statement.simple_op_assign:
            names = statement.lhs
        else:
            names = statement.names
        for name in names:
            if name == target_name:
                continue
            answers, nested_signatures = self.find_statements_for_var(
                file_path, name, False
            )
            total_ans.extend(answers)
            signatures.extend(nested_signatures)
        return sorted(total_ans, key=lambda item: item[1]), signatures

    def is_call_stmt(self,node: ast.stmt) -> bool:
        return _is_call_statement(node)

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
        return self.get_call_func_signatures(_call_target_name(node))

    def get_call_func_signatures(self, target_name: str) -> list:
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
        return _lhs(node)

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
        cache_key = None
        if Domain is None and self.analysis_cache is not None:
            cache_key = (self.file_name, file_path, var_name, is_for_defined)
            cached = self.analysis_cache.statement_result(cache_key)
            if cached is not None:
                return cached
            nodes_by_name = self.analysis_cache.file_analysis(file_path)
            candidate_nodes = nodes_by_name.get(var_name, ())
            compact_statements = True
        elif Domain is None:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = split_unpack_in_code(f.read())
            tree = ast.parse(source, filename=file_path)
            candidate_nodes = None
            compact_statements = False
        else:
            tree = Domain[0]
            source = Domain[1]
            domain_key = id(tree)
            nodes_by_name = self._domain_statement_indexes.get(domain_key)
            if nodes_by_name is None:
                nodes_by_name = defaultdict(list)
                for node in ast.walk(tree):
                    if not isinstance(node, stmt_types) or not hasattr(node, 'lineno'):
                        continue
                    names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
                    for name in names:
                        nodes_by_name[name].append(node)
                self._domain_statement_indexes[domain_key] = nodes_by_name
            candidate_nodes = nodes_by_name.get(var_name, ())
            compact_statements = False

        results = []
        func_sig_t = []
        func_sig_seen = set()
        nodes = candidate_nodes if candidate_nodes is not None else ast.walk(tree)
        for node in nodes:
            if compact_statements:
                if node.call_target is not None:
                    for signature in self.get_call_func_signatures(node.call_target):
                        _append_unique(func_sig_t, func_sig_seen, signature)
                if node.is_assign and is_for_defined:
                    other_data, nested_signatures = self.get_cached_assign_var(
                        node, file_path, var_name
                    )
                    results.extend(other_data)
                    for signature in nested_signatures:
                        _append_unique(func_sig_t, func_sig_seen, signature)
                results.append((node.code_line, node.lineno))
                continue
            if not isinstance(node, stmt_types) or not hasattr(node, 'lineno'):
                continue
            if candidate_nodes is None and not any(
                isinstance(child, ast.Name) and child.id == var_name
                for child in ast.walk(node)
            ):
                continue

            if self.is_call_stmt(node):
                call_node = node.value  # ast.Call
                func_sigs = self.get_call_func_names(call_node)
                for f in func_sigs:
                    _append_unique(func_sig_t, func_sig_seen, f)

            if isinstance(node, ast.Assign) and is_for_defined:
                other_data, temp_sig_list = self.get_assign_var(node, file_path, var_name, Domain)
                for d in other_data:
                    results.append(d)
                for f in temp_sig_list:
                    _append_unique(func_sig_t, func_sig_seen, f)
            lineno = node.lineno
            code_line = ast.unparse(node)
            results.append((code_line, lineno))

        seen = set()
        res = []
        for code_line, lineno in sorted(results, key=lambda x: x[1]):
            if lineno not in seen:
                res.append((code_line, lineno))
                seen.add(lineno)
        if cache_key is not None:
            self.analysis_cache.remember_statement_result(cache_key, res, func_sig_t)
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
        cache_key = None
        if self.analysis_cache is not None:
            cache_key = (self.file_name, data)
            cached = self.analysis_cache.use_result(cache_key)
            if cached is not None:
                return cached
        fix_srcCode  = split_unpack_in_code(data.source_code)
        param_all_data = [fix_srcCode]
        param_all_seen = {fix_srcCode}
        func_sig_used_list = []
        try:
            call_node = ast.parse(fix_srcCode)
            for i in ast.walk(call_node):
                if isinstance(i, ast.Call):
                    params_list = self.get_name_args_from_call(i)
                    for p_identify in params_list:
                        identify_slicing, sigs = self.find_statements_for_var(data.file_name, p_identify, False)
                        for s in identify_slicing:
                            _append_unique(param_all_data, param_all_seen, s[0])
                        for f in sigs:
                            func_sig_used_list.append(f)
                    break
        except Exception:
            logger.warning(f"analysizer use data error {data.name}, code:{fix_srcCode}")

        if cache_key is not None:
            self.analysis_cache.remember_use_result(
                cache_key, param_all_data, func_sig_used_list
            )
        return param_all_data, func_sig_used_list

    def function_use_data(
        self, function_name: str, excluded_signatures: Iterable[str] = ()
    ) -> list[str]:
        base_key = (self.file_name, function_name)
        events = None
        if self.analysis_cache is not None:
            events = self.analysis_cache.function_use_events(base_key)
        if events is None:
            built_events = []
            for use in self.Funcion_methods.get_function_use_data(function_name):
                data, signatures = self.parse_use_data(use)
                built_events.extend(("signature", value) for value in signatures)
                built_events.extend(("data", value) for value in data)
            events = tuple(built_events)
            if self.analysis_cache is not None:
                self.analysis_cache.remember_function_use_events(base_key, events)

        excluded = frozenset(excluded_signatures)
        output_key = (base_key, excluded)
        if self.analysis_cache is not None:
            cached = self.analysis_cache.function_output(output_key)
            if cached is not None:
                return cached

        values = []
        seen = set()
        definition_marker = "def " + function_name
        for kind, value in events:
            if kind == "signature" and (
                value in excluded or definition_marker in value
            ):
                continue
            _append_unique(values, seen, value)
        if self.analysis_cache is not None:
            self.analysis_cache.remember_function_output(output_key, values)
        return values

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
        call_node_seen = set()
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
                    _append_unique(call_node_str, call_node_seen, i)

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

        total_use_data = self.function_use_data(
            function_name, (*call_node_str, *func_sig_list)
        )

        function_code = ast.unparse(node)

        total_code = ""
        total_code_list = []
        total_code_seen = set()
        for f in call_node_str:
            _append_unique(total_code_list, total_code_seen, f)
        for i in func_return_data:
            _append_unique(total_code_list, total_code_seen, i)
        total_code_list.append(function_code)
        total_code_seen.add(function_code)
        for p in total_use_data:
            _append_unique(total_code_list, total_code_seen, p)

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
        total_code_seen = set()
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        if var_node != None:
            root1 = self.get_scope_node(root, var_node)

        may_cls_data = self.Funcion_methods.find_file_class_name(file_path, target_var_name)
        if may_cls_data!="":
            total_code_list.append(may_cls_data)
            total_code_seen.add(may_cls_data)
        res, sigs = self.find_statements_for_var(file_path, target_var_name, is_for_defined=True,
                                            Domain=(root1, source))

        total_code = ""
        import_infos = self.get_import_info(file_path, source)
        for i_f in import_infos:
            import_source = ast.get_source_segment(source, i_f)
            _append_unique(total_code_list, total_code_seen, import_source)
        for fs in sigs:
            _append_unique(total_code_list, total_code_seen, fs)
        for i in res:
            _append_unique(total_code_list, total_code_seen, i[0])
        total_code = "\n".join(total_code_list)
        self.add_high_recall_recommendations(target_var_name, total_code, file_path)
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
        total_code_seen = set()

        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()

        if func_node:
            func_name = func_node.name
            total_code = ""
            import_infos = self.get_import_info(file_path, source)
            for i_f in import_infos:
                import_source = ast.get_source_segment(source, i_f)
                _append_unique(total_code_list, total_code_seen, import_source)

            # params_node = get_function_params_node(func_node, param_name)
            lines = source.splitlines()
            params_line = self.get_signature_line(func_node)
            may_class = self.Funcion_methods.find_file_class_name(file_path, param_name)
            if may_class!="":
                total_code_list.append(may_class)
                total_code_seen.add(may_class)

            res, sigs = self.find_statements_for_var(file_path, param_name, is_for_defined=True, Domain=(func_node, ast.unparse(func_node)))
            for fs in sigs:
                _append_unique(total_code_list, total_code_seen, fs)
            function_code = ast.unparse(func_node)
            total_code_list.append(function_code)
            total_code_seen.add(function_code)

            total_use_data = self.function_use_data(func_name, sigs)
            for fu in total_use_data:
                _append_unique(total_code_list, total_code_seen, fu)

            total_code = "\n".join(total_code_list)
            self.add_high_recall_recommendations(
                param_name, total_code, file_path, function_name=func_name
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
