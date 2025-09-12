from typing import NamedTuple
from typing import List, Union, Iterable, Type
from dataclasses import dataclass
import ast

stmt_types = (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Expr, ast.Global, ast.Return)

class ProjectDefined(NamedTuple):
    name: str
    source_code: str

class ProjectUseData(NamedTuple):
    name: str
    source_code: str
    lineno: int
    file_name: str

class ProjectClassDefine(NamedTuple):
    name: str
    signature: str
    file_name: str

@dataclass
class FunctionInfo:
    name: str
    signature: str

@dataclass
class ClassInfo:
    name: str
    fields: List[str]
    methods: List[str]

OTHER_PROMPTS ={
    "init_type": "The type that initially passes static analysis is {}",
    "class":"The possible type of target is a class",
}
SIMPLE_BINOPS: Iterable[Type[ast.operator]] = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.FloorDiv,
    ast.Pow,
)


class OutPutData(NamedTuple):
    cat: str
    file: str
    generic: bool
    gttype: str
    loc: str
    name: str
    origttype: str
    processed_gttype: str
    scope: str
    type_depth: int
    code_slicing: str
    other_prompt: list
    prediction: List[str]
    total_prompt: str