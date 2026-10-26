"""Small, versioned structural builtin contracts (never inferred gold types)."""
VERSION = 'graph-builtin-contracts-v1'
CONTRACTS = {
    'map': 'callback applied to elements; result is iterable',
    'zip': 'result elements combine corresponding input elements',
    'enumerate': 'result elements pair index with input element',
    'iter': 'result iterates the input (two-argument form uses a sentinel)',
    'list': 'construction from iterable elements',
    'tuple': 'construction from iterable elements',
    'set': 'construction from iterable elements',
    'dict': 'construction from mapping or key/value pairs',
}


def builtin_contract(name, bound_names, monkey_patched=False):
    if monkey_patched or name in bound_names:
        return None
    return CONTRACTS.get(name)


def apply_builtin_contract(graph,call_id,call,name,version=VERSION):
    """Connect actual source operands to iterable-element evidence at a callsite."""
    import ast
    if name not in CONTRACTS:
        raise ValueError('Unknown builtin contract')
    if name=='map':
        operands=call.args[1:]
    elif name in {'enumerate','iter'}:
        operands=call.args[:1]
    else:
        operands=call.args
    for index,operand in enumerate(operands):
        for node in list(graph.nodes.values()):
            if node.id!=call_id and node.scope==graph.nodes[call_id].scope and node.span.start==operand.lineno and node.span.column==operand.col_offset:
                graph.link(node.id,call_id,'element',f'{version}:{name}:iterable_operand:{index}','verified')
    if name=='iter' and len(call.args)>1:
        graph.gap(call_id,'builtin_iter_sentinel_callback_not_closed')
