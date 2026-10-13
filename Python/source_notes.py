"""Preserve source comments attached to selected class declarations."""
import ast
import io
import tokenize


def class_notes(source, node):
    lines = source.splitlines()
    regions = []
    for member in node.body:
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [member.name]
        elif isinstance(member, (ast.Assign, ast.AnnAssign)):
            targets = member.targets if isinstance(member, ast.Assign) else [member.target]
            names = [n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)]
        else:
            continue
        first = min([member.lineno, *(d.lineno for d in getattr(member, 'decorator_list', ()))])
        while first > node.lineno + 1 and (not lines[first - 2].strip() or lines[first - 2].lstrip().startswith('#')):
            first -= 1
        regions.append((first, member.end_lineno, names, member))
    notes = {}
    try:
        comments = [t for t in tokenize.generate_tokens(io.StringIO(source).readline) if t.type == tokenize.COMMENT]
    except (tokenize.TokenError, IndentationError):
        return notes
    for token in comments:
        line = token.start[0]
        if not node.lineno <= line <= node.end_lineno:
            continue
        owners = next((names for first, last, names, member in regions if first <= line <= last), ['__class__'])
        for index, (_, _, names, member) in enumerate(regions):
            following = regions[index + 1][3].lineno if index + 1 < len(regions) else node.end_lineno + 1
            if member.lineno <= line < following and token.start[1] > member.col_offset:
                owners = names
                break
        for owner in owners:
            notes.setdefault(owner, []).append(token.string)
    return notes


def append_notes(definition, notes, members=None):
    """Notes stay comments, count against the same 8k candidate budget."""
    selected = set(notes) if members is None else set(members) | {'__class__'}
    extra = []
    for owner, values in notes.items():
        if owner in selected:
            for value in values:
                line = f"    # {owner}: {value.lstrip('# ').rstrip()}"
                if line.strip() not in definition:
                    extra.append(line)
    return '\n'.join([definition, *extra]) if extra else definition
