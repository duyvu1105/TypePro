"""Measure model-specific packing without downloading a model or project KB."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from typepro.data.preprocess import iter_records
from typepro.shared.context_packing import ContextBudgetError, ContextPacker, POLICY


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--model-name', required=True)
    parser.add_argument('--input-length', type=int, default=8192)
    parser.add_argument('--label-length', type=int, default=64)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()
    if args.label_length < 1 or args.input_length <= args.label_length or args.limit < 0:
        parser.error('Require input-length > label-length > 0 and limit >= 0')
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    packer = ContextPacker(tokenizer, args.input_length - args.label_length,
                           args.report.parent / 'packed_context_cache')
    counts, lengths, failures = Counter(), [], []
    for index, row in enumerate(iter_records(args.input)):
        if args.limit and index >= args.limit:
            break
        counts['rows'] += 1
        try:
            packed = packer.pack(row)
        except ContextBudgetError as exc:
            counts['mandatory_overflow'] += 1
            failures.append({'id': row.get('id'), 'error': str(exc)})
            continue
        counts[packed.audit['policy']] += 1
        counts['omitted_blocks'] += len(packed.audit.get('omitted', []))
        counts['summary_only_blocks'] += len(packed.audit.get('summary_only', []))
        counts['compact_only_blocks'] += len(packed.audit.get('compact_only', []))
        lengths.append(len(packed.token_ids))
    lengths.sort()
    report = dict(policy=POLICY, tokenizer=args.model_name,
                  tokenizer_fingerprint=packer.fingerprint,
                  input_length=args.input_length, label_length=args.label_length,
                  counts=dict(counts), failures=failures,
                  tokens={name: lengths[int((len(lengths)-1)*q)] for name, q in
                          [('p50', .5), ('p95', .95), ('max', 1)]} if lengths else {})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
    packer.close()
    print(json.dumps({k: v for k, v in report.items() if k != 'failures'}, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
