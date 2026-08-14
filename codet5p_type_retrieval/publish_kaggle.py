from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


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
    if shutil.which("kaggle") is None:
        raise RuntimeError("Install the Kaggle CLI first: pip install kaggle")
    metadata_path = data_dir / "dataset-metadata.json"
    metadata_path.write_text(json.dumps({
        "title": args.title,
        "id": args.dataset_id,
        "licenses": [{"name": "CC-BY-4.0"}],
    }, indent=2), encoding="utf-8")
    common = ["-p", str(data_dir), "--dir-mode", "zip"]
    # Query first: create only on a 404/non-zero result; otherwise add a version.
    exists = subprocess.run(
        ["kaggle", "datasets", "files", args.dataset_id],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0
    if exists:
        command = ["kaggle", "datasets", "version", *common, "-m", args.message]
    else:
        if args.public:
            common.append("--public")
        command = ["kaggle", "datasets", "create", *common]
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
