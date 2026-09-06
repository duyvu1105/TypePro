"""Per-example source overlays: analysis never reads the target annotation.

The checkout and shared ASTs stay unchanged. Each example owns its derived
indexes/caches; callers must not reuse gold-derived analysis in this context.
"""
import builtins
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
