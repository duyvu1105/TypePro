import re
def wrap_with_union(s: str) -> str:
    pattern = re.compile(r'dict\[\s*([^\[\]]+?)\s*\]')

    def repl(match: re.Match) -> str:
        inner = match.group(1)
        parts = []
        for p in inner.split(','):
            t = p.strip()
            if t.lower() == 'any':
                parts.append(t)
            else:
                parts.append(f'union[any, {t}]')
        return 'dict[' + ', '.join(parts) + ']'

    return pattern.sub(repl, s)


def convert_type_annotation(type_str: str) -> str:
    pattern = r"list\s*\[\s*([\w\.]+)\s*\]"
    match = re.search(pattern, type_str)

    if match:
        original_type = match.group(1).strip()
        return re.sub(pattern, f"list[Union[Any, {original_type}]]", type_str)
    else:
        return type_str


import ast


class UnpackSplitter(ast.NodeTransformer):

    def visit_Assign(self, node: ast.Assign):
        if (len(node.targets) == 1 and
                isinstance(node.targets[0], (ast.Tuple, ast.List))):

            targets = node.targets[0].elts
            value = node.value
            new_nodes = []
            for idx, elt in enumerate(targets):
                sub = ast.Subscript(
                    value=value,
                    slice=ast.Index(ast.Constant(idx)),
                    ctx=ast.Load()
                )
                new_nodes.append(
                    ast.Assign(targets=[elt], value=sub)
                )
            return new_nodes

        return self.generic_visit(node)


def split_unpack_in_code(src: str) -> str:
    try:
        tree = ast.parse(src)
        tree = UnpackSplitter().visit(tree)

        ast.fix_missing_locations(tree)
        return ast.unparse(tree)
    except:
        return src


import ast
from typing import Union

def attribute_to_string(node: Union[ast.Attribute, ast.Name, ast.Call, ast.Subscript]) -> str:

    if isinstance(node, ast.Name):
        return node.id


    if isinstance(node, ast.Attribute):

        prefix = attribute_to_string(node.value)
        return f"{prefix}.{node.attr}"

    if isinstance(node, ast.Call):
        func_str = attribute_to_string(node.func)
        return func_str + "()"

    if isinstance(node, ast.Subscript):
        value_str = attribute_to_string(node.value)
        if isinstance(node.slice, ast.Index): 
            idx = node.slice.value
        else:  
            idx = node.slice
        try:
            idx_str = ast.unparse(idx)
        except AttributeError:
            if isinstance(idx, ast.Constant):
                idx_str = repr(idx.value)
            else:
                idx_str = "?"
        return f"{value_str}[{idx_str}]"

    try:
        return ast.unparse(node)
    except Exception:
        return ""



if __name__ == "__main__":
    src = """
c, t1, t2 = qubits
x, (y, z) = foo()
a = b = bar()
"""
    print(split_unpack_in_code(src))
