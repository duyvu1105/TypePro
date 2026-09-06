import ast
from target_context import source_open as open
from loguru import logger
from typing import List, Union, Optional, Dict
import os
import re
import sys
from dataclasses import dataclass
import json
from loguru import logger
from BM25 import bm25_similarity
from difflib import SequenceMatcher
from collections import OrderedDict

from type_defined import FunctionInfo, ClassInfo

DefinitionInfo = Union[FunctionInfo, ClassInfo]
DEFINITION_CACHE: "OrderedDict[str, tuple[int, int, List[DefinitionInfo]]]" = OrderedDict()
DEFINITION_CACHE_LIMIT = 24
DEFAULT_RECALL_LIMIT = 20
STRUCTURAL_STOP_WORDS = {
    "and", "as", "async", "await", "class", "def", "else", "false", "for",
    "from", "if", "import", "in", "none", "not", "or", "pass", "return",
    "self", "true", "with", "yield",
}
class importAnalyzer:

    def __init__(self, file_path:str):
        configured = os.environ.get("TYPEPRO_THIRD_PARTY_DATASET", "./Third-party-data/dataset/")
        self.datasets_paths = [path for path in configured.split(os.pathsep) if path]
        self.file_path = file_path
        self.packages = self.analyze_imports(file_path)
        self.detail_import_data = self.analyze_imports_detail(file_path)
        total_list,dict_data = self.load_all_package_data()
        self.total_data = total_list
        self.total_dict = dict_data
        self.classes_by_name = {}
        for item in self.total_data:
            if not isinstance(item, ClassInfo):
                continue
            self.classes_by_name.setdefault(item.name.casefold(), []).append(item)


    def analyze_imports(self, file_path: str) -> List[str]:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                src = f.read()
            tree = ast.parse(src)
        except Exception:
            return []

        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split('.')[0])
        return list(imports)

    def load_all_package_data(self)->List[DefinitionInfo]:
        total_data_t = []
        dict_data = {}
        for package_name in self.packages:
            for dataset_path in self.datasets_paths:
                total_path_name = os.path.join(dataset_path, package_name + ".json")
                if os.path.isfile(total_path_name):
                    temp_data = self.load_definitions_from_json(total_path_name)
                    dict_data.setdefault(package_name, []).extend(temp_data)
                    total_data_t.extend(temp_data)
        return total_data_t, dict_data

    def load_definitions_from_json(self, file_name: str) -> List[DefinitionInfo]:
        stat_info = os.stat(file_name)
        cached = DEFINITION_CACHE.get(file_name)
        if cached and cached[0] == stat_info.st_mtime_ns and cached[1] == stat_info.st_size:
            DEFINITION_CACHE.move_to_end(file_name)
            return cached[2]
        with open(file_name, "r", encoding="utf-8") as f:
            data = json.load(f)

        result: List[DefinitionInfo] = []
        for item in data:
            if item["type"] == "function":
                result.append(FunctionInfo(name=item["name"], signature=item["signature"]))
            elif item["type"] == "class":
                result.append(ClassInfo(
                    name=item["name"],
                    fields=item.get("fields", []),
                    methods=item.get("methods", []),
                    package=item.get("package", ""),
                    module=item.get("module", ""),
                    qualified_name=item.get("qualified_name", ""),
                    bases=item.get("bases", []),
                    definition=item.get("definition", ""),
                    source=item.get("source", "third_party"),
                    kind=item.get("kind", "class"),
                ))
        DEFINITION_CACHE[file_name] = (stat_info.st_mtime_ns, stat_info.st_size, result)
        DEFINITION_CACHE.move_to_end(file_name)
        while len(DEFINITION_CACHE) > DEFINITION_CACHE_LIMIT:
            DEFINITION_CACHE.popitem(last=False)
        return result

    def render_class(self, info: ClassInfo) -> str:
        if info.definition:
            lines = info.definition.splitlines()
            if info.source and not any("# source:" in line for line in lines):
                lines.insert(1, f"    # source: {info.source}")
            return "\n".join(lines)
        bases = f"({', '.join(info.bases)})" if info.bases else ""
        lines = [f"class {info.name}{bases}:"]
        if info.package:
            lines.append(f"    # package: {info.package}")
        if info.module:
            lines.append(f"    # module: {info.module}")
        if info.source:
            lines.append(f"    # source: {info.source}")
        if info.kind != "class":
            lines.append(f"    # kind: {info.kind}")
        if info.fields:
            lines.append("    # fields")
            lines.extend(f"    {value}" for value in info.fields)
        if info.methods:
            lines.append("    # public methods")
            lines.extend(f"    {value}" for value in info.methods)
        if len(lines) == 1:
            lines.append("    pass")
        return "\n".join(lines)

    def get_class_recommendations(
        self, target_name: str, limit: int = DEFAULT_RECALL_LIMIT
    ) -> List[str]:
        """Rank class definitions from packages imported by the target file."""
        target = target_name.rsplit(".", 1)[-1].replace("_", "").casefold()
        ranked = []
        for info in self.total_data:
            if not isinstance(info, ClassInfo):
                continue
            candidate = info.name.replace("_", "").casefold()
            similarity = SequenceMatcher(None, target, candidate).ratio()
            if target == candidate:
                similarity = 1.0
            elif target and candidate and (target in candidate or candidate in target):
                similarity = max(similarity, 0.8)
            if similarity > 0.2:
                ranked.append((similarity, info.qualified_name, self.render_class(info)))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        result = []
        seen = set()
        for _, _, definition in ranked:
            if definition not in seen:
                seen.add(definition)
                result.append(definition)
            if len(result) >= limit:
                break
        return result

    def _matching_classes(self, module: str, name: str) -> list[ClassInfo]:
        matches = []
        module_key = module.casefold().strip(".")
        for info in self.classes_by_name.get(name.casefold(), []):
            candidate_module = info.module.casefold()
            if (
                not module_key
                or candidate_module == module_key
                or candidate_module.startswith(module_key + ".")
            ):
                matches.append(info)
        return matches

    @staticmethod
    def _symbol_definition(module: str, name: str) -> str:
        package = module.split(".", 1)[0]
        source = "stdlib" if package in sys.stdlib_module_names else "import_symbol"
        return "\n".join([
            f"class {name}:",
            f"    # package: {package}",
            f"    # module: {module}",
            f"    # source: {source}",
            "    # kind: imported_symbol",
        ])

    def get_exact_import_recommendations(
        self, source: str | None = None, limit: int = 80
    ) -> List[str]:
        """Resolve directly imported classes and qualified class attributes."""
        if source is None:
            try:
                with open(self.file_path, "r", encoding="utf-8") as handle:
                    source = handle.read()
            except OSError:
                return []
        parse_source = source.replace("<mask>", "TYPEPRO_MASK")
        try:
            tree = ast.parse(parse_source, filename=self.file_path)
        except (SyntaxError, ValueError):
            tree = None

        definitions = []
        module_aliases: dict[str, str] = {}
        nodes = ast.walk(tree) if tree is not None else ()
        for node in nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_aliases[alias.asname or alias.name.split(".", 1)[0]] = alias.name
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    matches = self._matching_classes(node.module, alias.name)
                    for info in matches:
                        definitions.append(self.render_class(info))
                    if not matches and alias.name.isidentifier():
                        definitions.append(
                            self._symbol_definition(node.module, alias.name)
                        )
                    module_aliases[alias.asname or alias.name] = (
                        f"{node.module}.{alias.name}"
                    )

        nodes = ast.walk(tree) if tree is not None else ()
        for node in nodes:
            if not isinstance(node, ast.Attribute):
                continue
            parts = [node.attr]
            value = node.value
            while isinstance(value, ast.Attribute):
                parts.insert(0, value.attr)
                value = value.value
            if not isinstance(value, ast.Name) or value.id not in module_aliases:
                continue
            module = module_aliases[value.id]
            class_name = parts[-1]
            matches = self._matching_classes(module, class_name)
            for info in matches:
                definitions.append(self.render_class(info))
            if not matches and class_name.isidentifier():
                definitions.append(self._symbol_definition(module, class_name))

        if tree is None:
            fallback_aliases = {}
            for match in re.finditer(
                r"(?m)^\s*import\s+([\w.]+)(?:\s+as\s+(\w+))?", source
            ):
                module, alias = match.groups()
                fallback_aliases[alias or module.split(".", 1)[0]] = module
            for match in re.finditer(
                r"(?m)^\s*from\s+([\w.]+)\s+import\s+([^#\n]+)", source
            ):
                module = match.group(1)
                for item in match.group(2).split(","):
                    imported = item.strip().split(" as ", 1)[0].strip(" ()")
                    if not imported or imported == "*" or not imported.isidentifier():
                        continue
                    matches = self._matching_classes(module, imported)
                    definitions.extend(self.render_class(info) for info in matches)
                    if not matches:
                        definitions.append(self._symbol_definition(module, imported))
            for alias, module in fallback_aliases.items():
                for match in re.finditer(rf"\b{re.escape(alias)}\.([A-Za-z_]\w*)", source):
                    name = match.group(1)
                    matches = self._matching_classes(module, name)
                    definitions.extend(self.render_class(info) for info in matches)
                    if not matches:
                        definitions.append(self._symbol_definition(module, name))

        return list(dict.fromkeys(definitions))[:limit]

    def get_imported_module_inventory(
        self, target_name: str, limit_per_module: int = 100
    ) -> List[str]:
        """Expose root-module classes for ``import module`` statements."""
        try:
            with open(self.file_path, "r", encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=self.file_path)
        except (OSError, SyntaxError, ValueError):
            return []
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
        target = target_name.replace("_", "").casefold()
        definitions = []
        for module in dict.fromkeys(modules):
            matches = [
                info for info in self.total_data
                if isinstance(info, ClassInfo) and info.module == module
            ]
            matches.sort(key=lambda info: (
                -SequenceMatcher(
                    None, target, info.name.replace("_", "").casefold()
                ).ratio(),
                info.qualified_name,
            ))
            definitions.extend(
                self.render_class(info) for info in matches[:limit_per_module]
            )
        return list(dict.fromkeys(definitions))

    def get_total_data(self):
        return self.total_data

    def get_total_dict(self):
        return self.total_dict

    def is_file_package(self, function_name:str):
        if "." in function_name:
            package_name = function_name.split(".")[0]
        else:
            package_name = function_name
        for i in self.detail_import_data:
            p_name = ""

            if i["alias"] == None:
                p_name = i["module"]
            else:
                p_name = i["alias"]
            if p_name == package_name:
                return True
            elif "." in p_name and package_name in p_name.split("."):
                return True

        return False

    def find_call_package(self, function_name:str):
        package_name = function_name.split(".")[0]
        for i in self.detail_import_data:
            if i["alias"] == package_name:
                package_name = i["module"].split(".")[0]
                break

        if package_name in self.total_dict:
            return self.total_dict[package_name]
        else:
            return []

    def get_function_by_name(self,func_name:str)-> List[DefinitionInfo]:
        res = []
        if not self.is_file_package(func_name):
            return res

        package_list = self.find_call_package(function_name=func_name)
        if len(package_list) == 0:
            package_list.extend(self.total_data)

        if "." in func_name:
            func_name = func_name.split(".")[-1]
        for f in package_list:
            if f.name == func_name:
                res.append(f)
        return res

    def analyze_imports_detail(self, file_path: str) -> List[Dict[str, Optional[str]]]:

        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()

        tree = ast.parse(source, filename=file_path)

        imports = []

        name_to_index: Dict[str, int] = {}

        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name
                    asname = alias.asname
                    key = asname or module
                    idx = len(imports)
                    imports.append({'module': module, 'alias': asname, 'used': False})
                    name_to_index[key] = idx
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                for alias in node.names:
                    fullname = f"{module}.{alias.name}" if module else alias.name
                    asname = alias.asname
                    key = asname or alias.name
                    idx = len(imports)
                    imports.append({'module': fullname, 'alias': asname, 'used': False})
                    name_to_index[key] = idx

        class UsageVisitor(ast.NodeVisitor):
            def visit_Name(self, n: ast.Name):
                if n.id in name_to_index:
                    imports[name_to_index[n.id]]['used'] = True
                self.generic_visit(n)

            def visit_Attribute(self, n: ast.Attribute):

                value = n
                while isinstance(value, ast.Attribute):
                    value = value.value
                if isinstance(value, ast.Name) and value.id in name_to_index:
                    imports[name_to_index[value.id]]['used'] = True
                self.generic_visit(n)

        UsageVisitor().visit(tree)

        return imports

    def calculate_similarity_for_class(
        self, target: str, limit: int = DEFAULT_RECALL_LIMIT
    ):
        def structural_tokens(value: str) -> str:
            return " ".join(
                token.casefold()
                for token in re.findall(r"[A-Za-z_]\w*", value)
                if token.casefold() not in STRUCTURAL_STOP_WORDS
            )

        target_tokens = structural_tokens(target)
        ranked = []
        for info in self.total_data:
            if not isinstance(info, ClassInfo):
                continue
            definition = self.render_class(info)
            similarity = bm25_similarity(target_tokens, structural_tokens(definition))
            if similarity > 0.1:
                ranked.append((similarity, info.qualified_name, definition))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        result = []
        seen = set()
        for _, _, definition in ranked:
            if definition not in seen:
                seen.add(definition)
                result.append(definition)
            if len(result) >= limit:
                break
        return result

if __name__ == "__main__":
    pass
