"""Structural symbol resolution: imports, reexports and source-owned receivers.

The index contains no annotation information. All dispatch results identify
source declarations; open receiver dispatch is separately recorded as a gap.
"""
from __future__ import annotations
import ast
from collections import defaultdict
from typepro.analysis.graph_builder import FUNCTIONS


class SymbolIndex:
    def __init__(self, resolver, module_aliases=None):
        self.resolver = resolver
        self.aliases = dict(module_aliases or {})
        self.files = defaultdict(list)
        self.bindings = {}
        self.classes = {}
        for file, tree in resolver.trees.items():
            self.files[resolver.modules[file]].append(file)
            names = defaultdict(list)
            for stmt in tree.body:
                if isinstance(stmt, (*FUNCTIONS, ast.ClassDef)):
                    names[stmt.name].append(stmt)
                elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    for alias in stmt.names:
                        names[alias.asname or alias.name.split('.')[0]].append((stmt, alias))
                elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                    for target in targets:
                        for child in ast.walk(target):
                            if isinstance(child, ast.Name):
                                names[child.id].append(stmt)
            self.bindings[file] = names
            self._classes(file, tree)

    def _classes(self, file, tree, prefix=''):
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                qualified = f'{prefix}.{node.name}' if prefix else node.name
                self.classes[(file, qualified)] = node
                self._classes(file, node, qualified)

    def canonical(self, full):
        seen = set()
        while full not in seen:
            seen.add(full)
            matches = [a for a in self.aliases if full == a or full.startswith(a + '.')]
            if not matches:
                return full
            prefix = max(matches, key=len)
            full = self.aliases[prefix] + full[len(prefix):]
        return None

    def import_target(self, file, stmt, alias):
        if isinstance(stmt, ast.Import):
            return alias.name if alias.asname else alias.name.split('.')[0]
        package = self.resolver.modules[file].split('.')
        if not file.endswith('__init__.py'):
            package = package[:-1]
        base = stmt.module or ''
        if stmt.level:
            package = package[:max(0, len(package) - stmt.level + 1)]
            base = '.'.join([*package, *([base] if base else [])])
        return '.'.join(filter(None, (base, alias.name)))

    def _module_files(self, module):
        files = self.files.get(module, ())
        runtime = [f for f in files if f.endswith('.py')]
        return runtime or list(files)

    def full_references(self, full, seen=()):
        full = self.canonical(full)
        if full is None or full in seen:
            return [], 'reexport_cycle'
        parts = full.split('.')
        for split in range(len(parts), -1, -1):
            module, tail = '.'.join(parts[:split]), '.'.join(parts[split:])
            files = self._module_files(module)
            if files and tail:
                found = []
                reason = 'exact_import_or_reexport'
                for file in files:
                    values, rule = self.file_references(file, tail, (*seen, full))
                    found.extend(values)
                    if not values:
                        reason = rule
                unique = {(f, q, id(n)): (f, q, n) for f, q, n in found}
                return list(unique.values()), reason
        return [], 'external_source_unavailable'

    def file_references(self, file, expression, seen=()):
        root, _, suffix = expression.partition('.')
        bindings = self.bindings[file].get(root, ())
        if bindings:
            if len(bindings)>1 and not all(isinstance(b,FUNCTIONS) for b in bindings):
                return [],'ambiguous_module_binding'
            found = []
            for binding in bindings:
                if isinstance(binding, tuple):
                    stmt, alias = binding
                    full = self.import_target(file, stmt, alias)
                    if suffix:
                        full += '.' + suffix
                    values, rule = self.full_references(full, seen)
                    found.extend(values)
                elif isinstance(binding, (*FUNCTIONS, ast.ClassDef)):
                    if not suffix:
                        found.append((file, root, binding))
                    else:
                        qualified = expression
                        found.extend((d.file, d.qualified, d.node) for d in self.resolver.by_scope.get((file,qualified),()))
                        if (file, qualified) in self.classes:
                            found.append((file, qualified, self.classes[file, qualified]))
                elif isinstance(binding, (ast.Assign, ast.AnnAssign)):
                    value = binding.value
                    if isinstance(value, (ast.Name, ast.Attribute)):
                        reference = ast.unparse(value) + ('.' + suffix if suffix else '')
                        identity = f'{file}:{expression}'
                        if identity in seen:
                            return [], 'reexport_cycle'
                        values, rule = self.file_references(file, reference, (*seen, identity))
                        found.extend(values)
            return found, 'exact_import_or_reexport' if found else 'binding_not_statically_resolved'
        # Python wildcard import semantics: use declared __all__ when static,
        # otherwise only public names. Never search unrelated project modules.
        found = []
        for stmt in self.resolver.trees[file].body:
            if not isinstance(stmt, ast.ImportFrom):
                continue
            for alias in stmt.names:
                if alias.name != '*':
                    continue
                module = self.import_target(file, stmt, alias).removesuffix('.*')
                for source in self._module_files(module):
                    exports = None
                    declarations = self.bindings[source].get('__all__', ())
                    if declarations:
                        try:
                            exports = ast.literal_eval(declarations[-1].value)
                        except (ValueError, TypeError, AttributeError):
                            continue
                        if not isinstance(exports, (list, tuple)) or not all(isinstance(v, str) for v in exports):
                            continue
                    if (exports is not None and root not in exports) or (exports is None and root.startswith('_')):
                        continue
                    values, _ = self.full_references(module + '.' + expression, seen)
                    found.extend(values)
        return found, 'scoped_wildcard' if found else 'symbol_not_found'

    def local_import(self, definition, name, call):
        from typepro.analysis.graph_summaries import scope_nodes
        bindings = []
        for node in scope_nodes(definition.node):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                bindings.extend((node, a) for a in node.names if (a.asname or a.name.split('.')[0]) == name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == name:
                return None
        args = definition.node.args
        if any(a.arg == name for a in args.posonlyargs + args.args + args.kwonlyargs):
            return None
        if len(bindings) == 1 and bindings[0][0] in definition.node.body and bindings[0][0].lineno < call.lineno:
            return self.import_target(definition.file, *bindings[0])
        return None

    def class_references(self, definition, expression):
        values, _ = self.file_references(definition.file, ast.unparse(expression))
        return [(f, q, n) for f, q, n in values if isinstance(n, ast.ClassDef)]

    def receiver_classes(self, definition, receiver, call, seen=()):
        if not isinstance(receiver, ast.Name) or receiver.id in seen:
            return []
        name = receiver.id
        from typepro.analysis.graph_summaries import scope_nodes
        nodes = list(scope_nodes(definition.node))
        assignments = [(n, n.value) for n in nodes if isinstance(n, (ast.Assign, ast.AnnAssign))
                       and any(isinstance(t, ast.Name) and t.id == name
                               for t in (n.targets if isinstance(n, ast.Assign) else [n.target]))]
        if name in {'self', 'cls'} and not assignments:
            parent = definition.qualified.rsplit('.', 1)[0] if '.' in definition.qualified else ''
            if (definition.file, parent) in self.classes:
                return [(definition.file, parent, self.classes[definition.file, parent])]
        if len(assignments) == 1:
            stmt, value = assignments[0]
            if stmt not in definition.node.body or stmt.lineno >= call.lineno:
                return []
            if isinstance(value, ast.Call):
                return self.class_references(definition, value.func)
            if isinstance(value, ast.Name):
                return self.receiver_classes(definition, value, call, (*seen, name))
        return self.class_references(definition, receiver)

    def member_definitions(self, file, qualified, name, seen=()):
        key = (file, qualified)
        if key in seen or key not in self.classes:
            return []
        own = self.resolver.by_scope.get((file,qualified+'.'+name),[])
        if own:
            return own
        found = []
        owner = self.classes[key]
        # Following all branches is conservative for multiple inheritance; the
        # caller marks receiver dispatch as open rather than claiming MRO proof.
        for base in owner.bases:
            refs, _ = self.file_references(file, ast.unparse(base))
            for base_file, base_qualified, node in refs:
                if isinstance(node, ast.ClassDef):
                    found.extend(self.member_definitions(base_file, base_qualified, name, (*seen, key)))
        return found

    def is_builtin(self, definition, name, locally_bound=()):
        import builtins
        if name not in vars(builtins) or name in locally_bound or self.bindings[definition.file].get(name):
            return False
        for stmt in ast.walk(self.resolver.trees[definition.file]):
            if isinstance(stmt,ast.ImportFrom) and any(a.name=='*' for a in stmt.names):
                return False
            if isinstance(stmt,ast.Call) and isinstance(stmt.func,ast.Name) and stmt.func.id=='setattr':
                return False
            if isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Name) and stmt.func.id in {'exec', 'globals'}:
                return False
            if isinstance(stmt, ast.Attribute) and isinstance(stmt.ctx, ast.Store):
                root = stmt.value
                if isinstance(root, ast.Name) and root.id in {'builtins', '__builtins__'}:
                    return False
        return True
