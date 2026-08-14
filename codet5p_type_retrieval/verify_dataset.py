from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a cached TypePro Kaggle Dataset")
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()
    root = Path(args.data_dir)
    with (root / "manifest.json").open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    errors = []
    for split, expected in manifest["output"].items():
        path = root / expected["file"]
        if not path.exists():
            errors.append(f"missing {path}")
            continue
        actual_hash = sha256(path)
        actual_rows = sum(1 for line in path.open(encoding="utf-8") if line.strip())
        if actual_hash != expected["sha256"]:
            errors.append(f"{split}: sha256 mismatch")
        if actual_rows != expected["rows"]:
            errors.append(f"{split}: row count {actual_rows} != {expected['rows']}")
    if errors:
        raise SystemExit("Dataset verification failed:\n- " + "\n- ".join(errors))
    print(json.dumps({"verified": True, "schema": manifest["schema_version"], "output": manifest["output"]}, indent=2))
