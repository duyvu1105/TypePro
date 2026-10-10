"""Fail closed before publication; measure every exported raw context."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from preprocess_generative import format_input

POLICY = 'ast-context-v3-recursive-signature-first'
MASKING = 'typepro-shared-kb-masked-source-v7-resolved-bounded-context'
MAX_DEFINITION_CHARS = 16000


def audit(raw_dir: Path) -> dict:
    lengths = {'slice_chars': [], 'candidate_chars': [], 'input_chars': []}
    rows = 0
    unresolved = 0
    related = 0
    largest = []
    for path in sorted(raw_dir.glob('*.jsonl')):
        with path.open(encoding='utf-8') as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                where = f'{path}:{number}'
                if row.get('context_policy_version') != POLICY or row.get('target_masking_version') != MASKING:
                    raise ValueError(f'Incompatible context policy: {where}')
                if row.get('candidate_definition_max_chars') != MAX_DEFINITION_CHARS:
                    raise ValueError(f'Missing candidate length contract: {where}')
                candidates = row.get('recommendation_types', [])
                if len(candidates) > 10 or any(len(item['definition']) > MAX_DEFINITION_CHARS for item in candidates):
                    raise ValueError(f'Unbounded candidates: {where}')
                for item in row.get('recommendation_diagnostics', {}).get('context_reduction', []):
                    if item.get('callee'):
                        if item.get('resolution') != 'resolved' or not item.get('source_file') or not item.get('source_line'):
                            raise ValueError(f'Unproven related function: {where}')
                        related += 1
                    unresolved += item.get('mode') == 'unresolved'
                slice_text = row.get('interprocedural_slice', '')
                normalized = [{'type': c.get('name') or c.get('type'), 'definition': c['definition']} for c in candidates]
                text = format_input(row.get('name', ''), row.get('target_function', ''), row.get('scope', ''), slice_text, normalized)
                values = {'slice_chars': len(slice_text), 'candidate_chars': sum(len(c['definition']) for c in candidates), 'input_chars': len(text)}
                for key, value in values.items():
                    lengths[key].append(value)
                rows += 1
                largest.append({'file': path.name, 'line': number, 'target': row.get('target_function'), **values})
                largest = sorted(largest, key=lambda x: x['input_chars'], reverse=True)[:20]
    if not rows:
        raise ValueError('No raw contexts to audit')
    stats = {}
    for key, values in lengths.items():
        values.sort()
        stats[key] = {name: values[min(len(values) - 1, int((len(values) - 1) * quantile))]
                      for name, quantile in [('median', .5), ('p95', .95), ('p99', .99), ('max', 1)]}
    return {'verified': True, 'rows': rows, 'context_policy_version': POLICY,
            'candidate_definition_max_chars': MAX_DEFINITION_CHARS,
            'resolved_related_functions': related, 'unresolved_calls': unresolved,
            'character_lengths': stats, 'largest_inputs': largest}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--raw-dir', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    report = audit(args.raw_dir)
    args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'largest_inputs'}, indent=2), flush=True)


if __name__ == '__main__':
    main()
