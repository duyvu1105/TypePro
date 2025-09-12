import ast
from loguru import logger
from typing import List, Union, Optional, Dict
import os
from dataclasses import dataclass
import json
from loguru import logger
from BM25 import bm25_similarity

from type_defined import FunctionInfo, ClassInfo

DefinitionInfo = Union[FunctionInfo, ClassInfo]
class importAnalyzer:

    def __init__(self, file_path:str):
        self.datasets_path = "./Third-party-data/dataset/"
        self.file_path = file_path
        self.packages = self.analyze_imports(file_path)
        self.detail_import_data = self.analyze_imports_detail(file_path)
        total_list,dict_data = self.load_all_package_data()
        self.total_data = total_list
        self.total_dict = dict_data


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
            total_path_name = self.datasets_path + package_name+".json"
            if os.path.isfile(total_path_name):
                temp_data = self.load_definitions_from_json(total_path_name)
                dict_data[package_name] = temp_data
                total_data_t.extend(temp_data)
        return total_data_t, dict_data

    def load_definitions_from_json(self, file_name: str) -> List[DefinitionInfo]:
        with open(file_name, "r", encoding="utf-8") as f:
            data = json.load(f)

        result: List[DefinitionInfo] = []
        for item in data:
            if item["type"] == "function":
                result.append(FunctionInfo(name=item["name"], signature=item["signature"]))
            elif item["type"] == "class":
                result.append(ClassInfo(name=item["name"], fields=item["fields"], methods=item["methods"]))
        return result

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

    def calculate_similarity_for_class(self, target:str):
        pass


if __name__ == "__main__":
    pass