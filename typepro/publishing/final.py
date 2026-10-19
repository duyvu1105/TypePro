from __future__ import annotations

if __package__ in (None, ''):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path

from typepro.publishing.kaggle_dataset_utils import publish_dataset


def package_final(data_dir: Path, payload_dir: Path) -> dict[str, str]:
    """Keep every immutable KB while avoiding Kaggle's case-insensitive paths."""
    sources = sorted((data_dir / "project_kb").glob("*/knowledge_base.json"))
    groups: dict[str, list[Path]] = {}
    for source in sources:
        groups.setdefault(source.parent.name.casefold(), []).append(source)
    index = {}
    seen = set()
    payload_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(payload_dir / "typepro.analysis.project_kb.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
        for source in sources:
            slug = source.parent.name
            destination = slug
            if len(groups[slug.casefold()]) > 1:
                destination += "--" + hashlib.sha256(slug.encode("utf-8")).hexdigest()[:16]
            relative = f"project_kb/{destination}/knowledge_base.json"
            if relative.casefold() in seen:
                raise RuntimeError(f"Case-insensitive path collision: {relative}")
            seen.add(relative.casefold())
            index[slug] = relative
            # Kaggle extracts an uploaded ZIP beneath its filename stem
            # (project_kb/), so do not repeat that prefix inside the archive.
            bundle.write(source, relative.removeprefix("project_kb/"))
    for source in sorted(data_dir.iterdir()):
        if source.is_file() and source.name not in {
            "dataset-metadata.json", "MERGE_COMPLETE.json", "project_kb_index.json", "typepro.analysis.project_kb.zip"
        }:
            if source.name.casefold() in seen:
                raise RuntimeError(f"Case-insensitive path collision: {source.name}")
            seen.add(source.name.casefold())
            # Same filesystem: stage multi-GB JSONL files without duplicating them.
            os.link(source, payload_dir / source.name)
    (payload_dir / "project_kb_index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or version a Kaggle Dataset")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--dataset-id", required=True, help="Kaggle id: username/dataset-slug")
    parser.add_argument("--title", default="TypePro Generative Project-KB Dataset")
    parser.add_argument("--message", default="Update processed TypePro generative dataset")
    parser.add_argument("--public", action="store_true", help="Default is private")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir).resolve()
    required = [data_dir / name for name in ("train.jsonl", "validation.jsonl", "test.jsonl", "manifest.json")]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing processed dataset files: {missing}")
    project_kb = data_dir / "project_kb"
    if not project_kb.is_dir() or not any(project_kb.glob("*/knowledge_base.json")):
        raise FileNotFoundError(f"Missing final project knowledge bases: {project_kb}")
    with tempfile.TemporaryDirectory(prefix="typepro_final_publish_", dir=data_dir.parent) as temp:
        payload_dir = Path(temp)
        index = package_final(data_dir, payload_dir)
        print(f"Packaged {len(index)} project KBs with unique full paths", flush=True)
        publish_dataset(
            payload_dir,
            args.dataset_id,
            args.title,
            args.message,
            public=args.public,
        )


if __name__ == "__main__":
    main()
