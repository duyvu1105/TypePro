"""Small, signature-only supplements; no receiver or external body expansion."""
import ast

from ast_context_slicer import FUNCTIONS, lexical_nodes, static_body
from type_defined import FunctionInfo


def opaque(catalog, path, scope):
    nodes = list(lexical_nodes(scope))
    nodes.extend(n for s in static_body(catalog.trees[path].body)
                 if not isinstance(s, (*FUNCTIONS, ast.ClassDef)) for n in lexical_nodes(s))
    return any(isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del)) or
               isinstance(n, (ast.Global, ast.Nonlocal)) or
               isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and
               n.func.id in {'exec', 'eval', 'setattr', 'delattr', 'globals', 'locals', 'vars'} for n in nodes)


def imported_name(catalog, path, expression):
    chain = []
    while isinstance(expression, ast.Attribute):
        chain.insert(0, expression.attr)
        expression = expression.value
    if not isinstance(expression, ast.Name):
        return None
    bindings = catalog.module_bindings(path, expression.id)
    if len(bindings or ()) != 1 or not isinstance(bindings[0], tuple):
        return None
    statement, alias = bindings[0]
    if statement not in catalog.module_bodies[path] or alias.name == '*':
        return None
    if isinstance(statement, ast.ImportFrom):
        module = catalog.import_module(path, statement)
        if module is None:
            return None
        return '.'.join(filter(None, (module, alias.name, *chain)))
    return '.'.join([alias.name, *chain]) if alias.asname else '.'.join([expression.id, *chain])


def external_contract(catalog, analyzer, path, scope, call):
    if opaque(catalog, path, scope):
        return None
    qualified = imported_name(catalog, path, call.func)
    if not qualified:
        return None
    module, _, name = qualified.rpartition('.')
    if any(m == module.split('.')[0] or m.startswith(module.split('.')[0] + '.') for m in catalog.by_module):
        return None  # Project definitions never fall back to library name lookup.
    package = module.split('.')[0]
    matches = [info for info in analyzer.total_dict.get(package, ()) if isinstance(info, FunctionInfo)
               and info.name == name and (info.qualified_name == qualified or
               not info.qualified_name and not info.module and module == package or
               not info.qualified_name and info.module == module)]
    if len(matches) != 1:
        return None
    info = matches[0]
    signature = info.signature.strip()
    if signature.startswith('function '):
        signature = 'def ' + signature[len('function '):]
    try:
        node = ast.parse(signature.rstrip(':') + ':\n    pass').body[0]
    except (SyntaxError, ValueError):
        return None
    if not isinstance(node, FUNCTIONS) or node.name != name:
        return None
    return node, dict(callee=qualified, resolution='resolved', mode='signature_only',
        reason='explicit_external_contract', source_file=info.source_file,
        source_line=info.source_line, provenance_kind='kb_record')


def receiver_contract(catalog, path, scope, call):
    """Accept self/cls, a known construction, or an unmasked nominal contract.

    Unknown receivers deliberately remain unknown. Only one local class or
    explicit project import and single-base inheritance are supported.
    """
    if not isinstance(scope, FUNCTIONS) or not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name):
        return None
    if opaque(catalog, path, scope):
        return None
    receiver, method = call.func.value.id, call.func.attr
    def find_class(source_path, expression, seen=frozenset()):
        key = (source_path, ast.unparse(expression))
        if key in seen or len(seen) >= 16:
            return None
        if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
            try:
                expression = ast.parse(expression.value, mode='eval').body
            except SyntaxError:
                return None
        if isinstance(expression, ast.Name):
            bindings = catalog.module_bindings(source_path, expression.id)
            if len(bindings or ()) == 1 and isinstance(bindings[0], ast.ClassDef) and bindings[0] in catalog.module_bodies[source_path]:
                return source_path, bindings[0]
        qualified = imported_name(catalog, source_path, expression)
        if qualified:
            module, _, name = catalog.canonical_module(qualified).rpartition('.')
            paths = catalog.by_module.get(module, ())
            if len(paths) == 1:
                return find_class(paths[0], ast.Name(id=name, ctx=ast.Load()), seen | {key})
        return None
    bindings = catalog.bindings(scope, receiver)
    owner = None
    if len(bindings) == 1 and isinstance(bindings[0], ast.arg):
        parameter = bindings[0]
        if parameter.annotation is not None:
            owner = find_class(path, parameter.annotation)
        if owner is None and scope.args.args and parameter is scope.args.args[0] and receiver in {'self', 'cls'}:
            for node in catalog.module_bodies[path]:
                if isinstance(node, ast.ClassDef) and any(isinstance(n, FUNCTIONS) and n.lineno == scope.lineno and n.name == scope.name for n in node.body):
                    if catalog.module_bindings(path, node.name) == [node] and not any(isinstance(d, ast.Name) and d.id == 'staticmethod' for d in scope.decorator_list):
                        owner = path, node
    elif len(bindings) == 1 and isinstance(bindings[0], ast.Name):
        assignment = next((s for s in static_body(scope.body) if isinstance(s, (ast.Assign, ast.AnnAssign))
                           and s.lineno < call.lineno and bindings[0] in list(ast.walk(s))), None)
        if assignment is not None and isinstance(assignment.value, ast.Call):
            root = assignment.value.func
            root_name = root.id if isinstance(root, ast.Name) else root.value.id if isinstance(root, ast.Attribute) and isinstance(root.value, ast.Name) else ''
            if root_name and not catalog.bindings(scope, root_name):
                owner = find_class(path, root)
    seen = set()
    while owner is not None and (owner[0], owner[1].name) not in seen:
        source_path, cls = owner
        seen.add((source_path, cls.name))
        if opaque(catalog, source_path, ast.Module(body=[], type_ignores=[])) or cls.decorator_list or any(isinstance(n, FUNCTIONS) and n.name in {'__getattribute__', '__getattr__', '__setattr__'} for n in cls.body):
            return None
        if any(isinstance(n, ast.Attribute) and n.attr == method and isinstance(n.ctx, (ast.Store, ast.Del)) for n in ast.walk(cls)):
            return None
        members = catalog.bindings(cls, method)
        if members:
            if len(members) != 1 or not isinstance(members[0], FUNCTIONS):
                return None
            node = members[0]
            if any(not isinstance(d, ast.Name) or d.id not in {'staticmethod', 'classmethod'} for d in node.decorator_list):
                return None
            return node, dict(callee=f'{catalog.modules[source_path]}.{cls.name}.{method}',
                resolution='resolved', mode='signature_only', reason='known_receiver_contract',
                source_file=source_path, source_line=node.lineno, provenance_kind='project_signature')
        owner = find_class(source_path, cls.bases[0]) if len(cls.bases) == 1 else None
    return None
