"""Exact template accounting; evidence is atomic and prompts are never sliced."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from typepro.shared.generative_chat import chat_token_ids

VERSION = 'typepro-chat-packing-v1'


class BudgetExceeded(ValueError):
    def __init__(self, required, available):
        self.required, self.available = required, available
        super().__init__(f'budget_exceeded: prompt requires {required} tokens, available {available}')


def tokenizer_fingerprint(tokenizer):
    backend=None
    if hasattr(tokenizer,'backend_tokenizer'):
        backend=json.loads(tokenizer.backend_tokenizer.to_str())
        backend.pop('padding',None)
        backend.pop('truncation',None)
    semantic_options={'add_bos_token','add_eos_token','clean_up_tokenization_spaces','split_special_tokens',
                      'legacy','add_prefix_space','spaces_between_special_tokens'}
    payload = dict(version=VERSION, template=getattr(tokenizer, 'chat_template', None),
                   special_tokens=getattr(tokenizer, 'special_tokens_map', {}),
                   revision=getattr(tokenizer, 'init_kwargs', {}).get('_commit_hash'),
                   vocabulary=tokenizer.get_vocab() if hasattr(tokenizer, 'get_vocab') else None,
                   tokenizer_class=type(tokenizer).__name__,
                   backend=backend,
                   added_tokens=getattr(tokenizer,'added_tokens_decoder',{}),
                   initialization={k:v for k,v in getattr(tokenizer,'init_kwargs',{}).items() if k in semantic_options})
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def prompt_token_ids(tokenizer, instruction, input_length, label_length):
    if label_length < 1 or input_length <= label_length:
        raise ValueError('Require 0 < label_length < input_length')
    ids = chat_token_ids(tokenizer, instruction)
    available = input_length - label_length
    if len(ids) > available:
        raise BudgetExceeded(len(ids), available)
    return ids


def training_token_ids(tokenizer, instruction, response, input_length, label_length):
    prompt = prompt_token_ids(tokenizer, instruction, input_length, label_length)
    sequence = chat_token_ids(tokenizer, instruction, response)
    if sequence[:len(prompt)] != prompt:
        raise ValueError('Chat template did not preserve the prompt as a sequence prefix')
    completion = sequence[len(prompt):]
    if len(completion) > label_length:
        raise ValueError(f'Completion requires {len(completion)} tokens; label budget is {label_length}')
    return prompt, sequence


@dataclass
class PackedContext:
    instruction: str
    prompt_ids: list[int]
    retained: list[str]
    omitted: dict[str, str]
    required_tokens: int
    outcome: str


def pack_groups(tokenizer, groups, render, input_length, label_length):
    available = input_length - label_length
    if label_length < 1 or available < 1:
        raise ValueError('Invalid token budget')
    by_id = {g.id: g for g in groups}
    if len(by_id) != len(groups):
        raise ValueError('Duplicate evidence group ID')

    def closure(identifier, visiting=None):
        visiting = set() if visiting is None else visiting
        if identifier not in by_id:
            raise ValueError('Missing group prerequisite')
        if identifier in visiting:
            return set()
        visiting.add(identifier)
        for prerequisite in by_id[identifier].prerequisites:
            closure(prerequisite, visiting)
        return visiting

    selected = set()
    for group in groups:
        if group.mandatory:
            selected |= closure(group.id)

    def materialize(ids):
        instruction = render([by_id[k] for k in sorted(ids)])
        return instruction, chat_token_ids(tokenizer, instruction)

    instruction, tokens = materialize(selected)
    required = len(tokens)
    if required > available:
        return PackedContext(instruction, tokens, sorted(selected),
                             {g.id: 'mandatory_budget_exceeded' for g in groups if g.id not in selected},
                             required, 'budget_exceeded')
    omitted = {}
    pending={g.id for g in groups if g.id not in selected}
    while pending:
        retained_nodes={n for identifier in selected for n in by_id[identifier].node_ids}
        choices=[]
        for identifier in sorted(pending):
            group=by_id[identifier]
            trial=selected|closure(identifier)
            trial_instruction,trial_tokens=materialize(trial)
            novel={n for key in trial-selected for n in by_id[key].node_ids}-retained_nodes
            rank=(group.priority,-len(novel),group.distance,len(trial_tokens)-len(tokens),group.id)
            choices.append((rank,identifier,trial,trial_instruction,trial_tokens))
        _,identifier,trial,trial_instruction,trial_tokens=min(choices,key=lambda c:c[0])
        pending.remove(identifier)
        if len(trial_tokens)<=available:
            selected,instruction,tokens=trial,trial_instruction,trial_tokens
            pending-=selected
        else:
            omitted[identifier]='marginal_token_budget'
    # Groups pulled in as prerequisites must not also appear as omitted.
    omitted = {k: v for k, v in omitted.items() if k not in selected}
    return PackedContext(instruction, tokens, sorted(selected), omitted, required, 'ready')
