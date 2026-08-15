from __future__ import annotations

import argparse
from pathlib import Path

from kaggle_dataset_utils import publish_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or version a Kaggle Dataset")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--dataset-id", required=True, help="Kaggle id: username/dataset-slug")
    parser.add_argument("--title", default="TypePro CodeT5+ Contrastive Dataset")
    parser.add_argument("--message", default="Update processed TypePro contrastive dataset")
    parser.add_argument("--public", action="store_true", help="Default is private")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir).resolve()
    required = [data_dir / name for name in ("train.jsonl", "validation.jsonl", "test.jsonl", "manifest.json")]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing processed dataset files: {missing}")
    publish_dataset(
        data_dir,
        args.dataset_id,
        args.title,
        args.message,
        public=args.public,
    )


if __name__ == "__main__":
    main()
