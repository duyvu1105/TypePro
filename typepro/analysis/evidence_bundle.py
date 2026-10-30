"""Tokenizer-independent, sample-local evidence exported where the KB lives."""
from __future__ import annotations

import hashlib
import ast

SCHEMA = 'typepro-evidence-v1'
RETRIEVAL_SCHEMA = 'typepro-project-kb-top10-generative-v18-sample-evidence'


def block(kind, text, *, required=False, priority=0, source=None, summary=None):
    identity = hashlib.sha256((kind + '\0' + text).encode()).hexdigest()[:24]
    return dict(id=identity, kind=kind, text=text, required=required,
                priority=priority, depends_on=[], source=source or {},
                **({'summary': summary} if summary else {}))


def compact_definition(definition):
    """Offer a source-derived middle level; keep full text as the final level.

    Preserve method return/control dependencies and uses of explicit parameters.
    Conservative reducer fallbacks remain whole. No return annotation is inferred
    or invented. Non-method class declarations remain unchanged.
    """
    from typepro.analysis.ast_context_slicer import FUNCTIONS, reduce_function
    from typepro.analysis.target_context import MASK, render_masks
    try:
        tree = ast.parse(definition.replace('<mask>', MASK))
    except (SyntaxError, ValueError, RecursionError):
        return None

    def reduce(node):
        if isinstance(node, FUNCTIONS):
            args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            args += [a for a in (node.args.vararg, node.args.kwarg) if a]
            parameters = [a.arg for a in args if a.arg not in {'self', 'cls'}]
            return reduce_function(node, parameters, returns=True).node
        if isinstance(node, ast.ClassDef):
            node.body = [reduce(child) for child in node.body]
        return node

    tree.body = [reduce(node) for node in tree.body]
    compact = render_masks(ast.unparse(ast.fix_missing_locations(tree)))
    if len(compact) < len(definition):
        return compact
    return None


def build_bundle(code, callers, candidates, source):
    """Keep target/callee closure atomic; only verified caller closures are optional.

    Do not split arbitrary statements or infer dependencies from rendered names.
    Each caller already includes its argument data/control and alias closure.
    If it cannot be separated exactly, retain it in the mandatory core instead.
    """
    core = code
    supplements = []
    for caller in callers:
        text = caller['text'].strip()
        if not text or '<mask>' in text or text == core.strip():
            continue
        wrapped = '\n' + core + '\n'
        needle = '\n' + text + '\n'
        if wrapped.count(needle) != 1:
            continue
        reduced = wrapped.replace(needle, '\n', 1).strip()
        if not reduced or '<mask>' not in reduced:
            continue
        core = reduced
        supplements.append(block('caller', text, priority=80, source=caller['source']))
    root = block('core', core, required=True, priority=100, source=source)
    blocks = [root]
    for item in supplements:
        item['depends_on'] = [root['id']]
        blocks.append(item)
    for rank, item in enumerate(candidates):
        header = f"[TYPE] {item['name']}\n[QUALIFIED_NAME] {item['qualified_name']}"
        entry = block('candidate', header + '\n[DEFINITION]\n' + item['definition'],
                      summary=header, priority=70 - rank, source=item.get('source_location'))
        compact = compact_definition(item['definition'])
        if compact:
            entry['compact'] = header + '\n[DEFINITION]\n' + compact
        entry['depends_on'] = [root['id']]
        blocks.append(entry)
    # Duplicate callers/candidates may have identical content.
    bundle = {'schema': SCHEMA, 'blocks': list({b['id']: b for b in blocks}.values())}
    validate_bundle(bundle)
    return bundle


def validate_bundle(bundle):
    if not isinstance(bundle, dict) or bundle.get('schema') != SCHEMA:
        raise ValueError('Unsupported evidence schema')
    blocks = bundle.get('blocks')
    if not isinstance(blocks, list) or not blocks:
        raise ValueError('Evidence bundle has no blocks')
    ids = set()
    for b in blocks:
        if not isinstance(b, dict) or not isinstance(b.get('id'), str) or b['id'] in ids:
            raise ValueError('Invalid or duplicate evidence identity')
        ids.add(b['id'])
        if b.get('kind') not in {'core', 'caller', 'candidate'}:
            raise ValueError('Invalid evidence kind')
        if not isinstance(b.get('text'), str) or not b['text'].strip():
            raise ValueError('Empty evidence text')
        if not isinstance(b.get('required'), bool) or not isinstance(b.get('priority'), (int, float)):
            raise ValueError('Invalid evidence selection metadata')
        if 'summary' in b and (b['kind'] != 'candidate' or not isinstance(b['summary'], str) or not b['summary']):
            raise ValueError('Invalid evidence summary')
        if 'compact' in b and (b['kind'] != 'candidate' or not isinstance(b['compact'], str) or not b['compact']):
            raise ValueError('Invalid compact evidence')
        if not isinstance(b.get('source'), dict) or not isinstance(b.get('depends_on'), list):
            raise ValueError('Invalid evidence provenance/dependencies')
    roots = [b for b in blocks if b['kind'] == 'core' and b['required']]
    if len(roots) != 1:
        raise ValueError('Evidence requires exactly one mandatory core')
    by_id = {b['id']: b for b in blocks}
    def visit(key, path):
        if key in path:
            raise ValueError('Cyclic evidence dependency')
        for dep in by_id[key]['depends_on']:
            if not isinstance(dep, str) or dep not in ids:
                raise ValueError('Missing evidence dependency')
            visit(dep, path | {key})
    for key in ids:
        visit(key, set())
    return bundle
