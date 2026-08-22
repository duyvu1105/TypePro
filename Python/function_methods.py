import json
from typing import List
from collections import namedtuple
from BM25 import bm25_similarity
from readFunctionDefined import total_function_data
from type_defined import ProjectDefined, ProjectUseData, ProjectClassDefine
from loguru import logger
from difflib import SequenceMatcher
import ast
from collections import defaultdict
from type_signal_analyzer import ProjectTypeAnalyzer

IGNORE_FUNCTION_NAME = ["bind", "get", "set"]

class Function_methods:
    project_data_path = "./data/project_function_defined.json"
    project_use_path = "./data/project_function_use.json"
    project_class_path  = "./data/project_class_defined.json"
    minimum_similarity_standard = 0.78
    recall_limit = 20

    @classmethod
    def empty(cls):
        instance = cls.__new__(cls)
        instance.total_function_data = []
        instance.total_function_use_data = []
        instance.total_class_data = []
        instance.project_type_analyzer = ProjectTypeAnalyzer(None)
        instance._rebuild_indexes()
        return instance

    def __init__(self, project_root: str | None = None, parsed_files=None):
        self.total_function_data = self.read_projects_from_json(self.project_data_path)
        self.total_function_use_data = self.read_projects_from_json2(self.project_use_path)
        self.total_class_data = self.read_project_class_from_json(self.project_class_path)
        self.project_type_analyzer = ProjectTypeAnalyzer(project_root, parsed_files)
        self._rebuild_indexes()

    def _rebuild_indexes(self):
        if not hasattr(self, "project_type_analyzer"):
            self.project_type_analyzer = ProjectTypeAnalyzer(None)
        self._function_sources_by_name = defaultdict(list)
        self._function_sources_by_qualified_name = defaultdict(list)
        self._function_definitions_by_file_and_name = defaultdict(list)
        self._function_uses_by_name = defaultdict(list)
        self._function_uses_by_qualified_name = defaultdict(list)
        self._unqualified_function_uses_by_name = defaultdict(list)
        self._names_with_qualified_uses = set()
        self._classes_by_name = defaultdict(list)
        for item in self.total_function_data:
            self._function_sources_by_name[item.name].append(item.source_code)
            if item.qualified_name:
                self._function_sources_by_qualified_name[item.qualified_name].append(
                    item.source_code
                )
            if item.file_name:
                key = (self._normalized_path(item.file_name), item.name)
                self._function_definitions_by_file_and_name[key].append(item)
        for item in self.total_function_use_data:
            self._function_uses_by_name[item.name].append(item)
            if item.qualified_name:
                self._function_uses_by_qualified_name[item.qualified_name].append(item)
                self._names_with_qualified_uses.add(item.name)
            else:
                self._unqualified_function_uses_by_name[item.name].append(item)
        for item in self.total_class_data:
            self._classes_by_name[item.name].append(item.signature)
        self._class_name_similarity_cache = {}
        self._file_class_cache = {}
        self._exact_import_cache = {}

    @staticmethod
    def _normalized_path(value: str) -> str:
        return str(value).replace("\\", "/").casefold()

    def load_func_data(self):

        self.total_function_data = self.read_projects_from_json(self.project_data_path)

        self.total_function_use_data = self.read_projects_from_json2(self.project_use_path)
        self._rebuild_indexes()

    def read_projects_from_json(self, filename: str) -> List[ProjectDefined]:
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

    def read_projects_from_json2(self, filename: str) -> List[ProjectUseData]:
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                projects_data = json.load(f)

            return [ProjectUseData(**item) for item in projects_data]

        except FileNotFoundError:
            print(f"{filename} does not exist")
            return []
        except json.JSONDecodeError:
            print(f"{filename} Not a valid JSON format")
            return []

    def read_project_class_from_json(self, filename: str) -> List[ProjectClassDefine]:
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                projects_data = json.load(f)

            return [ProjectClassDefine(**item) for item in projects_data]

        except FileNotFoundError:
            print(f"{filename} does not exist")
            return []
        except json.JSONDecodeError:
            print(f"{filename} Not a valid JSON format")
            return []

    def get_target_name_signals(self, target_name: str) -> list[str]:
        # logger.info(total_function_data)
        if target_name in IGNORE_FUNCTION_NAME :
            return []
        res = list(self._function_sources_by_qualified_name.get(target_name, ()))
        if not res:
            res = list(self._function_sources_by_name.get(target_name, ()))
        if "." in target_name and len(res) == 0:
            new_name = target_name.split(".")[-1]
            res = list(self._function_sources_by_name.get(new_name, ()))
        return res

    def get_class_by_names(self, target_name: str)-> list[str]:
        res = list(self._classes_by_name.get(target_name, ()))

        if "." in target_name:
            class_name = target_name.split(".")[0]
            res.extend(self._classes_by_name.get(class_name, ()))

        return res

    def resolve_function_qualified_name(
        self, file_path: str, func_name: str, class_name: str = ""
    ) -> str:
        """Resolve a function using its file and optional enclosing class.

        ``func_name`` alone is ambiguous for methods such as ``__init__``.  A
        class path (``Outer.Inner``) narrows the candidates to the exact
        qualified definition.  A dotted input is treated as an already
        qualified class/method name and is only accepted when it exists in the
        file index; otherwise we return it as a conservative fallback.
        """
        if "." in func_name and not class_name:
            candidates = [
                item.qualified_name
                for item in self.total_function_data
                if item.file_name
                and self._normalized_path(item.file_name) == self._normalized_path(file_path)
                and item.qualified_name.endswith(f".{func_name}")
            ]
            return candidates[0] if len(candidates) == 1 else func_name
        candidates = self._function_definitions_by_file_and_name.get(
            (self._normalized_path(file_path), func_name), ()
        )
        if class_name:
            suffix = f".{class_name}.{func_name}"
            candidates = tuple(
                item for item in candidates
                if item.qualified_name.endswith(suffix)
            )
        qualified_names = [item.qualified_name for item in candidates if item.qualified_name]
        return qualified_names[0] if len(qualified_names) == 1 else func_name

    def get_function_use_data(self, func_name: str) -> [ProjectUseData]:
        res = list(self._function_uses_by_qualified_name.get(func_name, ()))
        if "." in func_name:
            # Do not mix unresolved dynamic calls into a confidently qualified
            # function; that recreates the same-name collision this index avoids.
            leaf = func_name.rsplit(".", 1)[-1]
            if not res and leaf not in self._names_with_qualified_uses:
                # Backward compatibility for legacy indexes without qualified_name.
                return list(self._function_uses_by_name.get(leaf, ()))
            return res
        if not res:
            res = list(self._function_uses_by_name.get(func_name, ()))
        return res

    def get_function_data(self):
        return self.total_function_data

    def get_funtion_use_data(self):
        return self.total_function_use_data

    def calculate_similarity_for_class(self, target_code:str):

        choiceNumber = 5
        MinimumThreshold = 0.5
        res = []
        for cls in self.total_class_data:
            sim = bm25_similarity(target_code, cls.signature)
            if sim>MinimumThreshold:
                res.append((cls.signature, sim))

        res.sort(key=lambda x: x[1], reverse=True)
        if len(res)>choiceNumber:
            res = res[:choiceNumber]
        return res

    def get_import_info(self, file_path:str) -> [dict]:

        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        tree = ast.parse(source, filename=file_path)

        imports = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({
                        'type': 'import',
                        'module': alias.name,
                        'alias': alias.asname
                    })
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imports.append({
                        'type': 'from',
                        'module': node.module or '',
                        'name': alias.name,
                        'alias': alias.asname,
                        'level': node.level
                    })

        return imports

    def calculate_similarity_for_class_name(
        self, target_code: str, limit: int | None = None
    ):

        cached = self._class_name_similarity_cache.get(target_code)
        if cached is not None:
            return list(cached)

        choiceNumber = limit or self.recall_limit
        MinimumThreshold = 0.2
        res = []
        for cls in self.total_class_data:
            sim = self.similarity_difflib(target_code, cls.name)
            if sim>MinimumThreshold:
                res.append((cls.signature, sim))

        res.sort(key=lambda x: x[1], reverse=True)
        if len(res)>choiceNumber:
            res = res[:choiceNumber]
        new_lis = []
        for i in res:
            new_lis.append(i[0])
        self._class_name_similarity_cache[target_code] = tuple(new_lis)
        return new_lis

    def exact_imported_class_definitions(self, file_path: str) -> list[str]:
        """Return project class definitions named by direct/qualified imports."""
        cached = self._exact_import_cache.get(file_path)
        if cached is not None:
            return list(cached)
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=file_path)
        except (OSError, SyntaxError, ValueError):
            return []
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name != "*":
                        imported_names.add(alias.name)
        definitions = []
        for name in imported_names:
            definitions.extend(self._classes_by_name.get(name, ()))
        result = tuple(dict.fromkeys(definitions))
        self._exact_import_cache[file_path] = result
        return list(result)

    def semantic_type_recommendations(
        self, file_path: str, target_name: str, function_name: str = ""
    ) -> list[str]:
        return self.project_type_analyzer.recommendations(
            file_path, target_name, function_name
        )
    def find_file_class_name(self, file_path: str, name: str):
        cache_key = (file_path, name)
        if cache_key in self._file_class_cache:
            return self._file_class_cache[cache_key]

        for cls in self.total_class_data:
            if cls.file_name != file_path and cls.file_name.replace("\\","/") != file_path and cls.file_name.replace("/","\\") != file_path:
                continue
            if name.lower() == cls.name.lower() or self.similarity_difflib(name.lower(), cls.name.lower())>self.minimum_similarity_standard:
                self._file_class_cache[cache_key] = cls.signature
                return cls.signature

        import_info = self.get_import_info(file_path)
        import_name = []
        for i in import_info:
            if i["type"] == "import":
                import_name.append(i["module"])
            elif i["type"] == "from":
                import_name.append(i["name"])
        for cls in self.total_class_data:
            if cls.name not in import_name:
                continue
            elif name.lower() == cls.name.lower() or self.similarity_difflib(name.lower(), cls.name.lower())>self.minimum_similarity_standard:
                self._file_class_cache[cache_key] = cls.signature
                return cls.signature

        self._file_class_cache[cache_key] = ""
        return ""

    def similarity_difflib(self, a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

if __name__ == "__main__":
    pass

