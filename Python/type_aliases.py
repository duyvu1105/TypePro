"""Recognize source-declared type aliases without consulting target labels."""
import ast


TYPING_MODULES = {'typing', 'typing_extensions'}
TYPE_CONSTRUCTORS = {'NewType', 'TypeVar', 'ParamSpec', 'TypeVarTuple'}
TYPE_FORMS = {'Tuple', 'List', 'Dict', 'Set', 'FrozenSet', 'Sequence', 'Mapping',
              'MutableMapping', 'Iterable', 'Iterator', 'Optional', 'Union',
              'Callable', 'Annotated', 'Literal', 'Type', 'ClassVar', 'Final',
              'Awaitable', 'Coroutine', 'AsyncIterable', 'AsyncIterator', 'AsyncGenerator',
              'Generator', 'Collection', 'Container', 'MutableSequence', 'MutableSet',
              'Deque', 'DefaultDict', 'Counter', 'ChainMap', 'ContextManager',
              'AsyncContextManager', 'Reversible', 'Pattern', 'Match', 'IO', 'BinaryIO',
              'TextIO', 'TypeGuard', 'TypeIs', 'Concatenate', 'Required', 'NotRequired',
              'ReadOnly', 'Unpack'}


def typing_symbol(tree, expression):
    """Return a typing symbol only for an explicit, unique module binding."""
    from ast_context_slicer import FunctionCatalog, static_body
    root = expression.value if isinstance(expression, ast.Attribute) else expression
    if not isinstance(root, ast.Name):
        return None
    bindings = FunctionCatalog._bindings(tree, root.id)
    if len(bindings) != 1 or not isinstance(bindings[0], tuple):
        return None
    statement, alias = bindings[0]
    if statement not in tuple(static_body(tree.body)):
        return None
    if isinstance(expression, ast.Name) and isinstance(statement, ast.ImportFrom) and statement.module in TYPING_MODULES:
        return alias.name
    if isinstance(expression, ast.Attribute) and isinstance(statement, ast.Import) and alias.name in TYPING_MODULES:
        return expression.attr
    return None


def declared_aliases(tree):
    """Yield unconditional, unshadowed alias assignments with provenance.

    Implicit aliases require an identifiable typing/builtin type expression;
    uppercase runtime indexing such as Config = settings['x'] is not a type.
    """
    from ast_context_slicer import FunctionCatalog, static_body
    body = tuple(static_body(tree.body))
    classes = {n.name for n in body if isinstance(n, ast.ClassDef)
               and FunctionCatalog._bindings(tree, n.name) == [n]}
    recognized = set()
    def type_expression(value):
        if isinstance(value, ast.Subscript):
            base = value.value
            return typing_symbol(tree, base) in TYPE_FORMS or (
                isinstance(base, ast.Name) and base.id in {'list', 'dict', 'tuple', 'set', 'frozenset', 'type'}
                and not FunctionCatalog._bindings(tree, base.id))
        if isinstance(value, ast.BinOp) and isinstance(value.op, ast.BitOr):
            return type_expression(value.left) and type_expression(value.right)
        if isinstance(value, ast.Name):
            return value.id in recognized | classes or value.id in {'str', 'int', 'float', 'bytes', 'bool', 'object'} and not FunctionCatalog._bindings(tree, value.id)
        if isinstance(value, ast.Constant):
            return value.value is None
        return False
    for node in body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target, node.value
            explicit = typing_symbol(tree, node.annotation) == 'TypeAlias'
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value, explicit = node.targets[0], node.value, False
        else:
            continue
        if value is None or FunctionCatalog._bindings(tree, target.id) != [target]:
            continue
        constructor = typing_symbol(tree, value.func) if isinstance(value, ast.Call) else None
        if explicit or (target.id.lstrip('_')[:1].isupper() and
                        (type_expression(value) or constructor in TYPE_CONSTRUCTORS)):
            recognized.add(target.id)
            yield target.id, value, node, constructor
