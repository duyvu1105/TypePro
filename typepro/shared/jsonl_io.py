"""Read ordinary or gzip JSONL splits without materializing an expanded copy."""
import gzip
import json
from pathlib import Path


def open_text(path, mode='rt'):
    path = Path(path)
    if '.gz' in path.suffixes:
        return gzip.open(path, mode=mode, encoding='utf-8', compresslevel=1)
    return path.open(mode.replace('t', ''), encoding='utf-8')


def split_path(root, split):
    root = Path(root)
    manifest = root / 'manifest.json'
    if manifest.is_file():
        value = json.loads(manifest.read_text(encoding='utf-8'))
        filename = value.get('output', {}).get(split, {}).get('file')
        if filename:
            if Path(filename).name != filename:
                raise ValueError('Split manifest must name a file in the dataset directory')
            return root / filename
    plain = root / f'{split}.jsonl'
    compressed = root / f'{split}.jsonl.gz'
    return plain if plain.exists() or not compressed.exists() else compressed
