"""Convert legacy breadth-first TypeGen labels to Python annotation syntax.

This is a representation conversion, not type inference. No source or gold
annotation is consulted, and unparseable labels fail explicitly.
"""
import ast
import re


def normalize_type_label(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    if any(token in value for token in ('<eol>', '<eot>', '<kvsep>', '<typesep>')):
        if not value.endswith('<eot>'):
            raise ValueError(f'Incomplete serialized type: {value!r}')
        levels = value[:-5].strip().split('<eol>')
        root = [levels[0].strip(), []]
        frontier = [root]
        for level in levels[1:]:
            if not level.strip():
                frontier = []
                continue
            groups = level.split('<typesep>')
            if len(groups) != len(frontier):
                raise ValueError(f'Ambiguous serialized type level: {value!r}')
            following = []
            for parent, group in zip(frontier, groups):
                # Dictionary and Callable separate key/arguments from result.
                chunks = group.split('<kvsep>')
                if len(chunks) > 2:
                    raise ValueError(f'Invalid key/value separator: {value!r}')
                if parent[0] == 'Callable' and len(chunks) == 2:
                    args = [[x, []] for x in chunks[0].split()]
                    results = [[x, []] for x in chunks[1].split()]
                    if len(results) != 1:
                        raise ValueError(f'Invalid Callable result: {value!r}')
                    parent[1] = [['__args__', args], *results]
                    following.extend(args + results)
                else:
                    children = [[x, []] for x in group.replace('<kvsep>', ' ').split()]
                    parent[1] = children
                    following.extend(children)
            frontier = following

        def render(node):
            name, children = node
            if name == '__args__':
                return '[' + ', '.join(render(x) for x in children) + ']'
            return name + ('[' + ', '.join(render(x) for x in children) + ']' if children else '')

        value = render(root)
    if value == 'none':
        value = 'None'
    if re.search(r'<(?:eol|eot|kvsep|typesep)>', value):
        raise ValueError(f'Unconverted type label: {value!r}')
    try:
        return ast.unparse(ast.parse(value, mode='eval').body)
    except SyntaxError as error:
        raise ValueError(f'Invalid Python type label: {value!r}') from error
