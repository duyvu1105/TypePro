"""Create a separate Python-label dataset; quarantine unconvertible targets."""
import argparse
import hashlib
import json
from pathlib import Path

from type_labels import normalize_type_label


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    summary = {'label_format': 'python-annotation-v1', 'source_directory': str(args.input_dir.resolve()), 'splits': {}}
    with (args.output_dir / 'rejected_labels.jsonl').open('w', encoding='utf-8') as rejected:
        for split in ('train', 'validation', 'test'):
            stats = {'rows': 0, 'changed': 0, 'rejected': 0}
            digest = hashlib.sha256()
            with (args.input_dir / f'{split}.jsonl').open(encoding='utf-8') as source, (args.output_dir / f'{split}.jsonl').open('wb') as output:
                for line in source:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    original = row['label']
                    try:
                        row['label'] = normalize_type_label(original)
                    except ValueError as error:
                        rejected.write(json.dumps({'split': split, 'row': row, 'reason': str(error)}, ensure_ascii=False) + '\n')
                        stats['rejected'] += 1
                        continue
                    stats['changed'] += row['label'] != original
                    stats['rows'] += 1
                    payload = (json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8')
                    output.write(payload)
                    digest.update(payload)
            stats['sha256'] = digest.hexdigest()
            summary['splits'][split] = stats
    (args.output_dir / 'normalization_manifest.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
