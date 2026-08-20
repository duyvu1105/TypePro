from __future__ import annotations

import argparse
import shutil
import zipfile
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


def archive_project_kb(data_dir: Path) -> Path:
    """Zip the project KBs into ``project_kb.zip`` and free the source tree.

    The Kaggle CLI's default ``--dir-mode skip`` drops directories, so the
    final Dataset keeps ``project_kb/<owner>__<repo>/knowledge_base.json``
    inside ``project_kb.zip``; the training notebook restores them before
    verification.
    """
    kb_dir = data_dir / "project_kb"
    if not kb_dir.is_dir():
        raise ValueError(f"No project KB directory in {data_dir}")
    kb_files = sorted(kb_dir.rglob("knowledge_base.json"))
    if not kb_files:
        raise ValueError(f"No project knowledge bases found in {kb_dir}")
    archive = data_dir / "project_kb.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in kb_files:
            bundle.write(path, path.relative_to(data_dir).as_posix())
            path.unlink()
    shutil.rmtree(kb_dir, ignore_errors=True)
    return archive


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir).resolve()
    required = [data_dir / name for name in ("train.jsonl", "validation.jsonl", "test.jsonl", "manifest.json")]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing processed dataset files: {missing}")
    archive_project_kb(data_dir)
    publish_dataset(
        data_dir,
        args.dataset_id,
        args.title,
        args.message,
        public=args.public,
    )


if __name__ == "__main__":
    main()
