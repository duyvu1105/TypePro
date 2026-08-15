"""Package one completed TypePro build shard and publish it safely to Kaggle."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from kaggle_dataset_utils import publish_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish a completed TypePro shard")
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--payload-dir", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--message", default="Update completed TypePro shard")
    parser.add_argument("--expected-shard-index", required=True, type=int)
    parser.add_argument("--expected-shard-count", required=True, type=int)
    parser.add_argument("--public", action="store_true")
    return parser.parse_args()


def read_manifest(work_dir: Path) -> dict[str, Any]:
    path = work_dir / "shard_manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid shard manifest {path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError(f"Expected JSON object in {path}")
    selected = manifest.get("selected_projects")
    attempted = manifest.get("attempted_projects")
    if not isinstance(selected, int) or selected <= 0 or attempted != selected:
        raise RuntimeError(
            f"Shard is incomplete: selected={selected!r}, attempted={attempted!r}"
        )
    if manifest.get("missing_projects") != []:
        raise RuntimeError(
            f"Shard has missing projects: {manifest.get('missing_projects')!r}"
        )
    return manifest


def included(relative: PurePosixPath) -> bool:
    if not relative.parts:
        return False
    if relative.parts[0] == "raw_slices":
        return relative.suffix == ".jsonl"
    if relative.parts[0] == "project_status":
        return relative.suffix == ".json"
    if relative.parts[0] == "metadata":
        return relative.suffix == ".json"
    return len(relative.parts) == 1 and relative.name in {
        "runtime_manifest.json",
        "shard_manifest.json",
    }


def package_shard(work_dir: Path, payload_dir: Path) -> tuple[Path, dict[str, Any]]:
    work_dir = work_dir.resolve()
    manifest = read_manifest(work_dir)
    shard_index = manifest.get("shard_index")
    shard_count = manifest.get("shard_count")
    if not isinstance(shard_index, int) or not isinstance(shard_count, int):
        raise RuntimeError(f"Invalid shard coordinates: {manifest}")
    required = [
        work_dir / "metadata" / "split_manifest.json",
        work_dir / "raw_slices",
        work_dir / "project_status",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"Missing merge inputs: {missing}")

    directory_name = f"typepro_build_shard_{shard_index:02d}"
    payload_dir.mkdir(parents=True, exist_ok=True)
    archive = payload_dir / f"{directory_name}.zip"
    seen: dict[str, str] = {}
    counts = {"metadata": 0, "raw_slices": 0, "project_status": 0, "root": 0}
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(work_dir.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = PurePosixPath(path.relative_to(work_dir).as_posix())
            if not included(relative):
                continue
            output_name = f"{directory_name}/{relative.as_posix()}"
            canonical = output_name.casefold()
            previous = seen.get(canonical)
            if previous is not None:
                raise RuntimeError(
                    f"Case-insensitive path collision: {previous!r} and {output_name!r}"
                )
            parts = PurePosixPath(output_name).parts
            parents = {
                PurePosixPath(*parts[:index]).as_posix().casefold()
                for index in range(1, len(parts))
            }
            blocked_by = next((seen[parent] for parent in parents if parent in seen), None)
            if blocked_by:
                raise RuntimeError(
                    f"File/directory path collision: {blocked_by!r} blocks {output_name!r}"
                )
            child = next(
                (name for key, name in seen.items() if key.startswith(canonical + "/")),
                None,
            )
            if child:
                raise RuntimeError(
                    f"File/directory path collision: {output_name!r} blocks {child!r}"
                )
            seen[canonical] = output_name
            bundle.write(path, output_name)
            counts[relative.parts[0] if len(relative.parts) > 1 else "root"] += 1

    if counts["metadata"] == 0 or counts["raw_slices"] == 0 or counts["project_status"] == 0:
        raise RuntimeError(f"Packaged shard is missing required file groups: {counts}")
    print(json.dumps({
        "archive": str(archive),
        "archive_bytes": archive.stat().st_size,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "files": counts,
    }, indent=2))
    return archive, manifest


def main() -> None:
    args = parse_args()
    payload_dir = Path(args.payload_dir).resolve()
    _, manifest = package_shard(Path(args.work_dir), payload_dir)
    if (
        manifest["shard_index"] != args.expected_shard_index
        or manifest["shard_count"] != args.expected_shard_count
    ):
        raise RuntimeError(
            "Refusing to publish a shard from a different layout: "
            f"manifest={manifest['shard_index']}/{manifest['shard_count']}, "
            f"expected={args.expected_shard_index}/{args.expected_shard_count}"
        )
    expected_slug = f"typepro-build-shard-{manifest['shard_index']:02d}"
    actual_slug = args.dataset_id.rsplit("/", 1)[-1]
    if actual_slug != expected_slug:
        raise RuntimeError(
            f"Dataset slug {actual_slug!r} does not match shard {expected_slug!r}"
        )
    publish_dataset(
        payload_dir,
        args.dataset_id,
        args.title,
        args.message,
        public=args.public,
    )


if __name__ == "__main__":
    main()
