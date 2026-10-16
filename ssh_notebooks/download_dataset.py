"""Stream the private TypePro Kaggle Dataset to disk without buffering in RAM."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import quote

import requests


DATASET = "duyvu1105/typepro-python-generative"
FILES = (
    "DATASET_CARD.md",
    "manifest.json",
    "preprocess_stats.json",
    "project_split_map.json",
    "test.jsonl",
    "test_projects.txt",
    "test_split_audit.json",
    "train.jsonl",
    "validation.jsonl",
)
CHUNK_SIZE = 8 * 1024 * 1024
REPORT_BYTES = 256 * 1024 * 1024


def load_auth(path: Path) -> tuple[str, str]:
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise PermissionError(f"Credential must use mode 600, got {mode:o}: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    username = value.get("username")
    key = value.get("key")
    if not isinstance(username, str) or not isinstance(key, str):
        raise ValueError("kaggle.json must contain string username and key fields")
    return username, key


def download_file(
    session: requests.Session,
    auth: tuple[str, str],
    owner: str,
    slug: str,
    name: str,
    destination: Path,
) -> None:
    target = destination / name
    url = (
        "https://www.kaggle.com/api/v1/datasets/download/"
        f"{quote(owner)}/{quote(slug)}/{quote(name)}"
    )
    with session.get(url, auth=auth, stream=True, timeout=(30, 600)) as response:
        response.raise_for_status()
        expected = int(response.headers.get("Content-Length", 0))
        if target.is_file() and expected and target.stat().st_size == expected:
            print(f"skip {name}: already complete ({expected:,} bytes)", flush=True)
            return
        temporary = target.with_suffix(target.suffix + ".part")
        written = 0
        next_report = REPORT_BYTES
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if not chunk:
                    continue
                handle.write(chunk)
                written += len(chunk)
                if written >= next_report:
                    print(f"download {name}: {written:,} bytes", flush=True)
                    next_report += REPORT_BYTES
        if expected and written != expected:
            raise IOError(f"Incomplete {name}: expected {expected}, wrote {written}")
        os.replace(temporary, target)
        print(f"complete {name}: {written:,} bytes", flush=True)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--credential", type=Path, default=root / "kaggle.json")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "datasets" / "typepro-python-generative",
    )
    args = parser.parse_args()
    auth = load_auth(args.credential)
    owner, slug = DATASET.split("/", 1)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        for name in FILES:
            download_file(session, auth, owner, slug, name, args.output_dir)


if __name__ == "__main__":
    main()
