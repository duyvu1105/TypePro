"""Per-example source overlays: analysis never reads the target annotation.

The checkout, shared ASTs and project KB stay unchanged. Each example owns
its masked signature copies and slicing caches. KB metadata is not rewritten.
"""
import builtins
import ast
from contextlib import contextmanager
from contextvars import ContextVar
import io
from pathlib import Path
import re

MASK = '__TYPEPRO_TARGET_MASK__'
_sources = ContextVar('typepro_target_sources', default={})


@contextmanager
def source_overlay(path, source):
    token = _sources.set({str(Path(path).resolve()): source})
    try:
        yield
    finally:
        _sources.reset(token)


def source_open(file, mode='r', *args, **kwargs):
    if isinstance(file, (str, Path)) and mode in ('r', 'rt'):
        source = _sources.get().get(str(Path(file).resolve()))
        if source is not None:
            return io.StringIO(source)
    return builtins.open(file, mode, *args, **kwargs)


def read_source(path):
    with source_open(path, encoding='utf-8') as handle:
        return handle.read()


def mask_annotation(source, annotation):
    """Replace an AST annotation using UTF-8 byte offsets, preserving lines."""
    lines = source.encode('utf-8').splitlines(keepends=True)
    start = sum(map(len, lines[:annotation.lineno - 1])) + annotation.col_offset
    end = sum(map(len, lines[:annotation.end_lineno - 1])) + annotation.end_col_offset
    raw = source.encode('utf-8')
    # Parentheses keep multiline replacements syntactically valid.
    replacement = ('(' + MASK + '\n' * raw[start:end].count(b'\n') + ')').encode()
    return (raw[:start] + replacement + raw[end:]).decode('utf-8')


def render_masks(text):
    return re.sub(r'\b' + MASK + r'\b', '<mask>', text)


def mask_definition(text, function_name, target_name, scope):
    """Mask matching target annotations in a returned text copy, never in KB."""
    leaf = function_name.rsplit('.', 1)[-1]
    if not re.search(r'\b(?:def|function)\s+' + re.escape(leaf) + r'\s*\(', text):
        return text
    # Complete candidate definitions can be parsed as Python. Pseudo-signatures
    # and truncated definitions are handled one signature at a time below.
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        lines = text.splitlines(keepends=True)
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not re.match(r'(?:async\s+def|def|function)\s+' + re.escape(leaf) + r'\s*\(', stripped):
                continue
            probe = re.sub(r'^function\s+', 'def ', stripped).rstrip(':') + ':\n    pass'
            try:
                ast.parse(probe)
            except SyntaxError:
                # Fail closed for a matching signature we cannot safely parse.
                return '# target definition omitted: incomplete signature\n'
            masked = mask_definition(probe, function_name, target_name, scope).splitlines()[0]
            if stripped.startswith('function '):
                masked = masked.replace('def ', 'function ', 1).rstrip(':')
            lines[i] = line[:len(line) - len(line.lstrip())] + masked + '\n'
        return ''.join(lines)
    annotations = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == leaf:
            if scope == 'return' and node.returns is not None:
                annotations.append(node.returns)
            elif scope == 'arg':
                args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
                args += [a for a in (node.args.vararg, node.args.kwarg) if a]
                annotations.extend(a.annotation for a in args if a.arg == target_name and a.annotation is not None)
    for annotation in sorted(annotations, key=lambda n: (n.lineno, n.col_offset), reverse=True):
        text = mask_annotation(text, annotation)
    return text
