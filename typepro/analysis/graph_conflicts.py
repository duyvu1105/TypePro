"""Report contradictory explicit declarations; never infer or overwrite types."""
import ast
from collections import defaultdict


def annotation_conflicts(groups):
    claims=defaultdict(lambda:defaultdict(set))
    for group in groups:
        try:
            tree=ast.parse(group.text)
        except SyntaxError:
            continue
        def visit(node,owner):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                owner=owner+'.'+node.name if owner and not owner.endswith(node.name) else owner or node.name
            if isinstance(node,ast.AnnAssign):
                claims[(group.file,owner,ast.unparse(node.target))][ast.unparse(node.annotation)].add(group.id)
            for child in ast.iter_child_nodes(node):
                visit(child,owner)
        visit(tree,group.owner)
    return [dict(file=file,owner=owner,symbol=symbol,
                 declarations=[dict(annotation=a,groups=sorted(ids)) for a,ids in sorted(values.items())])
            for (file,owner,symbol),values in sorted(claims.items()) if len(values)>1]
