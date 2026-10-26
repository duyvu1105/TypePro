"""Exact lexical/import resolution with callsite provenance and explicit gaps.

No fuzzy names, legacy reducers, annotation-driven shared indexes, or arbitrary
project-wide fixture name lookup. Dynamic receiver resolution is left open.
"""
from __future__ import annotations
import ast
from dataclasses import dataclass
from typepro.analysis.graph_builder import FUNCTIONS, functions, structural_tree
from typepro.analysis.graph_contracts import builtin_contract


@dataclass(frozen=True)
class Definition:
    file: str
    module: str
    qualified: str
    occurrence: int
    node: ast.AST

    @property
    def key(self):
        return self.file, self.qualified, self.occurrence


class GraphResolver:
    def __init__(self, sources, module_aliases=None):
        # sources: relative path -> source; module names are canonical paths.
        self.trees = {}
        self.definitions = {}
        self.modules = {}
        self.parse_failures = {}
        self._incoming_calls = None
        self.module_definitions = {}
        self.by_scope = {}
        for file, source in sorted(sources.items()):
            try:
                tree = structural_tree(source)
            except (SyntaxError, ValueError) as error:
                self.parse_failures[file] = type(error).__name__
                continue
            self.trees[file] = tree
            module = file.removesuffix('.pyi').removesuffix('.py').replace('/', '.')
            if module.startswith('src.'):
                module = module[4:]
            if module.endswith('.__init__'):
                module = module[:-9]
            self.modules[file] = module
            counts = {}
            for qualified, node in functions(tree):
                occurrence = counts.get(qualified, 0)
                counts[qualified] = occurrence + 1
                value = Definition(file, module, qualified, occurrence, node)
                self.definitions[value.key] = value
                self.by_scope.setdefault((file,qualified),[]).append(value)

        from typepro.analysis.graph_symbols import SymbolIndex
        self.symbols = SymbolIndex(self, module_aliases)

    @staticmethod
    def local_bindings(function):
        from typepro.analysis.graph_summaries import scope_nodes
        args=function.args
        result={a.arg for a in args.posonlyargs+args.args+args.kwonlyargs}
        result.update(a.arg for a in (args.vararg,args.kwarg) if a)
        for node in scope_nodes(function):
            if isinstance(node,ast.Name) and isinstance(node.ctx,ast.Store):
                result.add(node.id)
            elif isinstance(node,(ast.Import,ast.ImportFrom)):
                result.update(a.asname or a.name.split('.')[0] for a in node.names)
            elif isinstance(node,(*FUNCTIONS,ast.ClassDef)):
                result.add(node.name)
        return result

    @staticmethod
    def module_function(tree):
        body=[n for n in tree.body if not isinstance(n,(*FUNCTIONS,ast.ClassDef))]
        result=ast.FunctionDef(name='__typepro_module_evidence__',
            args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),
            body=body,decorator_list=[],lineno=1,col_offset=0,
            end_lineno=max((n.end_lineno for n in tree.body),default=1),end_col_offset=0)
        return ast.fix_missing_locations(result)

    def incoming_calls(self,key):
        if self._incoming_calls is None:
            from typepro.analysis.graph_summaries import scope_nodes
            incoming={k:[] for k in self.definitions}
            definitions=list(self.definitions.values())
            for file,tree in self.trees.items():
                definition=Definition(file,self.modules[file],'<module>',0,self.module_function(tree))
                self.module_definitions[file]=definition
                definitions.append(definition)
            for caller in definitions:
                bound=set() if caller.qualified=='<module>' else self.local_bindings(caller.node)
                for call in scope_nodes(caller.node):
                    if not isinstance(call,ast.Call):
                        continue
                    matches,rule=self.resolve(caller,call,bound)
                    if len(matches)==1:
                        incoming[matches[0].key].append((caller,call,rule))
            self._incoming_calls=incoming
        return self._incoming_calls.get(key,())

    def target(self, target):
        if target.occurrence is not None:
            return self.definitions.get((target.file, target.function, target.occurrence))
        matches = self.by_scope.get((target.file,target.function),[])
        return matches[0] if len(matches) == 1 else None

    def module_binding(self, definition, name):
        matches=[]
        for stmt in self.trees[definition.file].body:
            if isinstance(stmt, (*FUNCTIONS,ast.ClassDef)) and stmt.name==name:
                matches.append(stmt)
            elif isinstance(stmt,(ast.Import,ast.ImportFrom)):
                for alias in stmt.names:
                    if (alias.asname or alias.name.split('.')[0])==name:
                        matches.append(stmt)
            elif isinstance(stmt,(ast.Assign,ast.AnnAssign)):
                targets=stmt.targets if isinstance(stmt,ast.Assign) else [stmt.target]
                if any(isinstance(n,ast.Name) and n.id==name for t in targets for n in ast.walk(t)):
                    matches.append(stmt)
        return matches[0] if len(matches)==1 else None

    def resolve(self, definition, call, locally_bound):
        name=ast.unparse(call.func)
        root,_,suffix=name.partition('.')
        if isinstance(call.func,ast.Attribute):
            receivers=self.symbols.receiver_classes(definition,call.func.value,call)
            members=[]
            for file,qualified,_ in receivers:
                members.extend(self.symbols.member_definitions(file,qualified,call.func.attr))
            if members:
                return members,'receiver_member'
        if root in locally_bound:
            imported=self.symbols.local_import(definition,root,call)
            if imported:
                references,rule=self.symbols.full_references(imported+('.'+suffix if suffix else ''))
            else:
                return [],'local_callable_binding'
        else:
            parent=definition.qualified.rsplit('.',1)[0] if '.' in definition.qualified else ''
            if isinstance(call.func,ast.Name) and parent and (definition.file,parent) in self.by_scope:
                matches=self.by_scope.get((definition.file,parent+'.'+name),[])
                if matches:
                    return matches,'lexical_definition'
            references,rule=self.symbols.file_references(definition.file,name)
        matches=[]
        for file,qualified,node in references:
            matches.extend(d for d in self.by_scope.get((file,qualified),()) if d.node is node)
        if matches:
            direct=all(d.file==definition.file and d.qualified==name for d in matches)
            return matches,'lexical_definition' if direct else rule
        if isinstance(call.func,ast.Name) and self.symbols.is_builtin(definition,name,locally_bound):
            return [],('builtin:' if builtin_contract(name,()) else 'builtin_known:')+name
        return [],rule if rule in {'reexport_cycle','external_source_unavailable'} else 'dynamic_or_unresolved_callable'

    def bound_receiver(self, definition, call, callee):
        if not isinstance(call.func,ast.Attribute):
            return None
        decorators={ast.unparse(d) for d in callee.node.decorator_list}
        if 'staticmethod' in decorators:
            return None
        if 'classmethod' in decorators:
            return call.func.value
        receivers=self.symbols.receiver_classes(definition,call.func.value,call)
        # Class.method(instance, ...) is an unbound ordinary method access.
        if receivers and isinstance(call.func.value,ast.Name):
            direct=self.symbols.class_references(definition,call.func.value)
            if direct:
                return None
            return call.func.value
        return None


def bind_arguments(call, function, receiver=None):
    """Return actual AST -> formal name bindings; fail closed on expansions."""
    if any(isinstance(a, ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords):
        return None
    args = function.args
    positional = args.posonlyargs + args.args
    actuals=([receiver] if receiver is not None else [])+list(call.args)
    if len(actuals) > len(positional):
        return None  # variadic element correspondence is not established
    bindings = [(value, formal.arg) for value, formal in zip(actuals, positional)]
    assigned = {name for _, name in bindings}
    keyword_names = {a.arg for a in args.args + args.kwonlyargs}
    for keyword in call.keywords:
        if keyword.arg not in keyword_names or keyword.arg in assigned:
            return None
        bindings.append((keyword.value, keyword.arg))
        assigned.add(keyword.arg)
    defaults = dict(zip([a.arg for a in positional[len(positional) - len(args.defaults):]], args.defaults))
    defaults.update({a.arg: value for a, value in zip(args.kwonlyargs, args.kw_defaults) if value is not None})
    for formal in positional + args.kwonlyargs:
        if formal.arg not in assigned:
            if formal.arg not in defaults:
                return None
            bindings.append((defaults[formal.arg], formal.arg))
    return bindings
