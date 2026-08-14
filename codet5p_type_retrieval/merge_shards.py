from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge resumable TypePro build shards")
    parser.add_argument("--shard-build-dirs", nargs="+", required=True)
    parser.add_argument("--work-dir", required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def copy_checked(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256(source) != sha256(destination):
            raise ValueError(f"Conflicting shard file: {destination.name}")
        return
    shutil.copy2(source, destination)


def locate_build_dir(path: Path) -> Path:
    if (path / "metadata" / "split_manifest.json").exists():
        return path
    candidates = list(path.rglob("metadata/split_manifest.json"))
    if len(candidates) != 1:
        raise ValueError(f"Cannot uniquely locate typepro_build below {path}: {len(candidates)} matches")
    return candidates[0].parent.parent


def main() -> None:
    args = parse_args()
    destination = Path(args.work_dir).resolve()
    builds = [locate_build_dir(Path(value).resolve()) for value in args.shard_build_dirs]
    reference_manifest = None
    copied = {"raw_slices": 0, "project_status": 0}
    for build in builds:
        manifest_path = build / "metadata" / "split_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if reference_manifest is None:
            reference_manifest = manifest
            for metadata_file in (build / "metadata").glob("*.json"):
                copy_checked(metadata_file, destination / "metadata" / metadata_file.name)
            runtime = build / "runtime_manifest.json"
            if runtime.exists():
                copy_checked(runtime, destination / runtime.name)
        elif manifest != reference_manifest:
            raise ValueError(f"Shard split manifest differs: {build}")

        for directory, pattern in (("raw_slices", "*.jsonl"), ("project_status", "*.json"), ("project_status", "*.log")):
            for source in (build / directory).glob(pattern):
                copy_checked(source, destination / directory / source.name)
                copied[directory] += 1
    print(json.dumps({"merged_builds": [str(path) for path in builds], **copied}, indent=2))


if __name__ == "__main__":
    main()
