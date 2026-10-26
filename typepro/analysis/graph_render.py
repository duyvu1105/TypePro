"""Render source evidence, explicitly separating independent source fragments."""
from typepro.analysis.target_context import render_masks


def render_groups(target, groups):
    parts = [f'[TARGET_NAME] {target.name}',f'[TARGET_FUNCTION] {target.function}',
             f'[TARGET_SCOPE] {target.scope}',f'[SOURCE] {target.project}/{target.file}',
             '[SOURCE_EXCERPTS]']
    current_file=target.file
    for group in sorted(groups,key=lambda g:(g.file,g.start,g.end,g.id)):
        if group.file!=current_file:
            parts.append(f'# {group.file}')
            current_file=group.file
        visible=group.text.lstrip()
        names_own_header=any(visible.startswith(prefix+group.owner) for prefix in ('def ','async def ','class '))
        if group.owner and ('.' in group.owner or not names_own_header):
            parts.append(f'# {group.owner}')
        parts.append(render_masks(group.text))
    return '\n'.join(parts)


def render_function_excerpt(node, graph, scope, selected):
    """Prune statements while preserving their actual lexical/control wrappers.

    A gap in the scope retains that entire scope. An explicit excerpt marker in
    render_groups ensures omissions are never presented as executable originals.
    """
    import ast
    from copy import deepcopy
    local_nodes = [graph.nodes[k] for k in selected if graph.nodes[k].scope == scope
                   and graph.nodes[k].kind not in {'implicit_none', 'parameter'}]
    if any(graph.nodes[g['node']].scope == scope for g in graph.gaps):
        return ast.unparse(node)
    spans = [(n.span.start, n.span.end) for n in local_nodes]

    def relevant(stmt):
        return any(start <= stmt.end_lineno and end >= stmt.lineno for start, end in spans)

    def prune(statements):
        result = []
        for stmt in statements:
            if not relevant(stmt):
                continue
            clone = deepcopy(stmt)
            for name in ('body', 'orelse', 'finalbody'):
                if isinstance(getattr(clone, name, None), list):
                    body = prune(getattr(stmt, name))
                    if name == 'body' and not body:
                        body = [ast.Expr(value=ast.Constant(value=Ellipsis))]
                    setattr(clone, name, body)
            result.append(clone)
        return result

    result = deepcopy(node)
    result.body = prune(node.body) or [ast.Expr(value=ast.Constant(value=Ellipsis))]
    # Keep documentation as source evidence without treating its contents as
    # symbol-resolution facts.
    if ast.get_docstring(node) and (not result.body or not isinstance(result.body[0], ast.Expr)
                                 or not isinstance(result.body[0].value, ast.Constant)):
        result.body.insert(0, deepcopy(node.body[0]))
    return ast.unparse(ast.fix_missing_locations(result))
