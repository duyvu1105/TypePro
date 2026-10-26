"""Source-scoped pytest fixture declarations with explicit plugin provenance."""
from __future__ import annotations
import ast
from pathlib import PurePosixPath
from typepro.analysis.graph_builder import functions


def fixture_evidence(target, definition, overlays, resolver):
    records=[]
    gaps=[]
    parsed={}
    retained=set()
    scope_rank={'session':0,'package':1,'module':2,'class':3,'function':4}
    def tree(file):
        if file not in parsed:
            parsed[file]=ast.parse(overlays[file])
        return parsed[file]
    def sources(file):
        result=[file]
        directory=PurePosixPath(file).parent
        while True:
            path=str(directory/'conftest.py')
            if path in overlays and path not in result:
                result.append(path)
            if str(directory)=='.':
                break
            directory=directory.parent
        plugins=[]
        for path in list(result):
            for stmt in tree(path).body:
                if not isinstance(stmt,(ast.Assign,ast.AnnAssign)):
                    continue
                targets=stmt.targets if isinstance(stmt,ast.Assign) else [stmt.target]
                if not any(isinstance(n,ast.Name) and n.id=='pytest_plugins' for n in targets):
                    continue
                try:
                    names=ast.literal_eval(stmt.value)
                except (ValueError,TypeError):
                    gaps.append(('pytest_plugin_list_not_static',[path]))
                    continue
                names=[names] if isinstance(names,str) else names
                if not isinstance(names,(list,tuple)) or not all(isinstance(n,str) for n in names):
                    gaps.append(('pytest_plugin_list_not_static',[path]))
                    continue
                for name in names:
                    matches=[f for f,m in resolver.modules.items() if m==name] if resolver else []
                    if not matches:
                        gaps.append(('pytest_plugin_source_unavailable',[name]))
                    plugins.extend(matches)
        return list(dict.fromkeys([*result,*plugins]))
    def declarations(file,name,owner):
        pytest=set(); fixtures=set(); bound={}
        for stmt in tree(file).body:
            if isinstance(stmt,(ast.Import,ast.ImportFrom)):
                for alias in stmt.names:
                    local=alias.asname or alias.name.split('.')[0]
                    bound[local]=bound.get(local,0)+1
                    if isinstance(stmt,ast.Import) and alias.name=='pytest':
                        pytest.add(local)
                    if isinstance(stmt,ast.ImportFrom) and stmt.module=='pytest' and alias.name=='fixture':
                        fixtures.add(local)
            elif isinstance(stmt,ast.Assign):
                for lhs in stmt.targets:
                    if isinstance(lhs,ast.Name):
                        bound[lhs.id]=bound.get(lhs.id,0)+1
        pytest={n for n in pytest if bound[n]==1}
        fixtures={n for n in fixtures if bound[n]==1}
        matches=[]
        for qualified,node in functions(tree(file)):
            parent=qualified.rsplit('.',1)[0] if '.' in qualified else ''
            if parent and parent!=owner:
                continue
            for decorator in node.decorator_list:
                call=decorator if isinstance(decorator,ast.Call) else None
                expr=call.func if call else decorator
                known=isinstance(expr,ast.Name) and expr.id in fixtures
                known |= isinstance(expr,ast.Attribute) and isinstance(expr.value,ast.Name) and expr.value.id in pytest and expr.attr=='fixture'
                if not known:
                    continue
                public_name=node.name; fixture_scope='function'
                for keyword in call.keywords if call else ():
                    if keyword.arg in {'name','scope'}:
                        if not isinstance(keyword.value,ast.Constant) or not isinstance(keyword.value.value,str):
                            public_name=None
                            break
                        if keyword.arg=='name':
                            public_name=keyword.value.value
                        else:
                            fixture_scope=keyword.value.value
                if public_name==name:
                    matches.append((1 if parent else 0,node,fixture_scope))
        best=max((rank for rank,_,_ in matches),default=-1)
        return [(n,s) for rank,n,s in matches if rank==best]
    def visit(name,file,owner='',stack=(),request_scope=None,skip_file=None):
        candidates=sources(file)
        if skip_file in candidates:
            candidates=candidates[candidates.index(skip_file)+1:]
        found=[]
        for source in candidates:
            values=declarations(source,name,owner if source==file else '')
            if values:
                found=[(source,n,s) for n,s in values]
                break
        if len(found)!=1:
            gaps.append(('pytest_fixture_binding_unresolved',[name]))
            for source,node,scope in found:
                records.append((source,node,'pytest_ambiguous_fixture:'+name))
            return
        source,node,scope=found[0]
        key=(source,node.lineno,name)
        if key in stack:
            gaps.append(('pytest_fixture_dependency_cycle',[name,source]))
            return
        if request_scope in scope_rank and scope in scope_rank and scope_rank[scope]>scope_rank[request_scope]:
            gaps.append(('pytest_fixture_scope_mismatch',[name,scope,request_scope]))
        if key in retained:
            return
        retained.add(key)
        records.append((source,node,'pytest_scoped_fixture:'+name))
        args=node.args
        positional=args.posonlyargs+args.args
        mandatory=positional[:len(positional)-len(args.defaults)]
        mandatory+= [a for a,d in zip(args.kwonlyargs,args.kw_defaults) if d is None]
        for parameter in mandatory:
            if parameter.arg in {'self','cls'}:
                continue
            if parameter.arg=='request':
                gaps.append(('pytest_request_runtime_context',[source,node.name]))
                continue
            visit(parameter.arg,file,owner,(*stack,key),scope,source if parameter.arg==name else None)
    owner=definition.qualified.rsplit('.',1)[0] if '.' in definition.qualified else ''
    visit(target.name,definition.file,owner)
    return records,gaps
