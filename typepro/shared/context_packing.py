"""Pack complete evidence closures with the active model's chat tokenizer.

The exported dataset never depends on this tokenizer. Oversized mandatory
evidence is an explicit error, rather than an unnoticed change to its meaning.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3

from typepro.analysis.evidence_bundle import validate_bundle

POLICY = 'typepro-context-packing-v2'


class ContextBudgetError(ValueError):
    pass


@dataclass
class PackedContext:
    instruction: str
    token_ids: list[int]
    audit: dict


def render_evidence(row, blocks, levels):
    parts = [f"[TARGET_NAME] {row.get('target_name', row.get('name', ''))}",
             f"[TARGET_FUNCTION] {row.get('target_function', '')}",
             f"[TARGET_SCOPE] {row.get('target_scope', row.get('scope', ''))}",
             '[INTERPROCEDURAL_SLICE]']
    parts.extend(b['text'] for b in blocks if b['kind'] != 'candidate' and b['id'] in levels)
    parts.append('[RECOMMENDATION_TYPES]')
    parts.extend(b.get(levels[b['id']], b['text'])
                 for b in blocks if b['kind'] == 'candidate' and b['id'] in levels)
    return '\n'.join(parts)


def pack_context(row, tokenizer, prompt_limit):
    from typepro.shared.generative_chat import chat_token_ids
    if prompt_limit < 1:
        raise ValueError('Prompt budget must be positive')
    if 'evidence_bundle' not in row:
        # Old datasets remain readable; audit explicitly distinguishes their
        # historical prefix truncation from dependency-aware packing.
        text = row['input']
        ids = chat_token_ids(tokenizer, text)
        return PackedContext(text, ids[:prompt_limit], {
            'policy': 'legacy-prefix', 'tokens': min(len(ids), prompt_limit),
            'original_tokens': len(ids), 'truncated': len(ids) > prompt_limit,
        })
    bundle = validate_bundle(row['evidence_bundle'])
    blocks = bundle['blocks']
    by_id = {b['id']: b for b in blocks}
    levels = {}

    def closure(key, chosen, level='full'):
        for dep in by_id[key]['depends_on']:
            if dep not in chosen:
                closure(dep, chosen)
        chosen[key] = level

    def encode(chosen):
        text = render_evidence(row, blocks, chosen)
        return text, chat_token_ids(tokenizer, text)

    for b in blocks:
        if b['required']:
            closure(b['id'], levels)
    text, ids = encode(levels)
    if len(ids) > prompt_limit:
        raise ContextBudgetError(
            f"Sample {row.get('id', '<unknown>')}: mandatory evidence and chat template "
            f"need {len(ids)} tokens; budget={prompt_limit}. Increase input length "
            'or explicitly exclude this sample before training/inference.'
        )
    # Reserve candidate identities before spending tokens on extended bodies.
    ranked = sorted(blocks, key=lambda b: -b['priority'])
    attempts = [(b, 'summary') for b in ranked if b['kind'] == 'candidate']
    for b in ranked:
        if 'compact' in b:
            attempts.append((b, 'compact'))
        attempts.append((b, 'full'))
    for b, level in attempts:
        if b['required']:
            continue
        chosen = dict(levels)
        closure(b['id'], chosen, level)
        trial, trial_ids = encode(chosen)
        if len(trial_ids) <= prompt_limit:
            levels, text, ids = chosen, trial, trial_ids
    return PackedContext(text, ids, {
        'policy': POLICY, 'tokens': len(ids), 'budget': prompt_limit,
        'kept': levels, 'omitted': [b['id'] for b in blocks if b['id'] not in levels],
        'summary_only': [key for key, level in levels.items() if level == 'summary'],
        'compact_only': [key for key, level in levels.items() if level == 'compact'],
    })


class ContextPacker:
    """Optional disk cache bound to exact tokenizer, template, source and budget."""
    def __init__(self, tokenizer, prompt_limit, cache_dir=None):
        self.tokenizer, self.prompt_limit = tokenizer, prompt_limit
        self.cache = None
        if cache_dir is not None:
            from typepro.shared.generative_chat import SYSTEM_PROMPT
            backend = getattr(tokenizer, 'backend_tokenizer', None)
            identity = {
                'policy': POLICY, 'budget': prompt_limit, 'system': SYSTEM_PROMPT,
                'template': getattr(tokenizer, 'chat_template', None),
                'special_tokens': getattr(tokenizer, 'special_tokens_map', {}),
                'tokenizer': backend.to_str() if backend is not None else tokenizer.get_vocab(),
                'class': type(tokenizer).__name__,
                'init': getattr(tokenizer, 'init_kwargs', {}),
            }
            fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
            self.fingerprint = fingerprint
            directory = Path(cache_dir)
            directory.mkdir(parents=True, exist_ok=True)
            self.cache = sqlite3.connect(directory / (fingerprint + '.sqlite3'), timeout=60)
            self.cache.execute('CREATE TABLE IF NOT EXISTS prompts (key TEXT PRIMARY KEY, value TEXT NOT NULL)')

    def pack(self, row):
        # Labels never enter packing or its cache key.
        source = {key: row[key] for key in (
            'target_name', 'name', 'target_function', 'target_scope', 'scope',
            'evidence_bundle', 'input') if key in row}
        key = hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if self.cache is not None:
            saved = self.cache.execute('SELECT value FROM prompts WHERE key=?', (key,)).fetchone()
            if saved:
                return PackedContext(**json.loads(saved[0]))
        packed = pack_context(row, self.tokenizer, self.prompt_limit)
        if self.cache is not None:
            value = json.dumps(dict(instruction=packed.instruction, token_ids=packed.token_ids, audit=packed.audit))
            with self.cache:
                self.cache.execute('INSERT OR REPLACE INTO prompts VALUES (?, ?)', (key, value))
        return packed

    def close(self):
        if self.cache is not None:
            self.cache.close()
