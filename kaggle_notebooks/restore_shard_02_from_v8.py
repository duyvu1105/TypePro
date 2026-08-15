"""Restore the TypePro shard-02 dataset from Kaggle notebook version 8.

Run this script in a Kaggle notebook.  It downloads the persisted output of
``duyvu1105/create-dataset/versions/8``, validates that it really contains the
completed shard 02/05, and uploads the shard archive as a Kaggle Dataset.

Install/update kagglehub before running it::

    %pip install -q -U kagglehub
    !python /kaggle/input/<source>/kaggle_notebooks/restore_shard_02_from_v8.py

Kaggle notebooks are authenticated automatically.  Outside Kaggle, configure
``KAGGLE_API_TOKEN`` (or ``~/.kaggle/kaggle.json``) first.
"""

from __future__ import annotations

import argparse
import json
import shutil
import stat
import sys
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any


DEFAULT_NOTEBOOK = "duyvu1105/create-dataset/versions/8"
DEFAULT_DATASET = "duyvu1105/typepro-build-shard-02"
SHARD_DIRECTORY = "typepro_build_shard_02"
SHARD_ARCHIVE = f"{SHARD_DIRECTORY}.zip"
RECOVERY_MEMBERS = {
    "metadata",
    "project_status",
    "raw_slices",
    "runtime_manifest.json",
    "shard_manifest.json",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recreate the TypePro shard-02 Dataset from notebook version 8 output."
    )
    parser.add_argument("--notebook", default=DEFAULT_NOTEBOOK)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("/kaggle/working/restore_shard_02_v8"),
    )
    parser.add_argument(
        "--version-notes",
        default="Restore completed shard 02 from create-dataset notebook version 8",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Download, package, and validate without uploading the Dataset.",
    )
    parser.add_argument(
        "--reuse-download",
        action="store_true",
        help="Reuse an existing download instead of downloading version 8 again.",
    )
    args, unknown = parser.parse_known_args(argv)

    # Jupyter/Colab starts the kernel with ``-f <connection-file>``.  When this
    # file is executed with %run (or pasted into a cell), those launcher
    # arguments are visible through sys.argv even though they are unrelated to
    # this recovery script.
    remaining = list(unknown)
    while "-f" in remaining:
        index = remaining.index("-f")
        if index + 1 >= len(remaining):
            parser.error("argument -f: expected the Jupyter connection file")
        del remaining[index : index + 2]
    if remaining:
        parser.error(f"unrecognized arguments: {' '.join(remaining)}")

    return args


def _read_json(raw: bytes, source: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid JSON in {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected a JSON object in {source}")
    return value


def validate_manifest(manifest: dict[str, Any], source: str) -> None:
    """Refuse to publish an incomplete archive or the wrong shard."""
    if manifest.get("shard_index") != 2:
        raise RuntimeError(
            f"{source} is not shard 02: shard_index={manifest.get('shard_index')!r}"
        )
    if manifest.get("shard_count") != 5:
        raise RuntimeError(
            f"{source} was not built as one of five shards: "
            f"shard_count={manifest.get('shard_count')!r}"
        )

    missing = manifest.get("missing_projects")
    if missing != []:
        raise RuntimeError(f"{source} is incomplete: missing_projects={missing!r}")

    selected = manifest.get("selected_projects")
    attempted = manifest.get("attempted_projects")
    if not isinstance(selected, int) or selected <= 0:
        raise RuntimeError(f"{source} has invalid selected_projects={selected!r}")
    if attempted != selected:
        raise RuntimeError(
            f"{source} is incomplete: attempted_projects={attempted!r}, "
            f"selected_projects={selected!r}"
        )


def _valid_manifest_in_bundle(
    bundle: zipfile.ZipFile, archive: Path
) -> tuple[dict[str, Any], PurePosixPath]:
    candidates = sorted(
        PurePosixPath(name)
        for name in bundle.namelist()
        if PurePosixPath(name).name == "shard_manifest.json"
    )
    if not candidates:
        raise RuntimeError(f"Archive contains no shard_manifest.json: {archive}")

    errors: list[str] = []
    for manifest_path in candidates:
        source = f"{archive}!/{manifest_path}"
        try:
            manifest = _read_json(bundle.read(str(manifest_path)), source)
            validate_manifest(manifest, source)
            return manifest, manifest_path
        except RuntimeError as exc:
            errors.append(str(exc))
    raise RuntimeError("; ".join(errors))


def validate_archive(archive: Path) -> dict[str, Any]:
    if not zipfile.is_zipfile(archive):
        raise RuntimeError(f"Not a valid zip archive: {archive}")

    with zipfile.ZipFile(archive) as bundle:
        manifest, _ = _valid_manifest_in_bundle(bundle, archive)
        names = set(bundle.namelist())
        prefix = f"{SHARD_DIRECTORY}/"
        split_manifest = f"{prefix}metadata/split_manifest.json"
        if split_manifest not in names:
            raise RuntimeError(f"Archive does not contain {split_manifest}: {archive}")
        if not any(name.startswith(f"{prefix}raw_slices/") and name.endswith(".jsonl") for name in names):
            raise RuntimeError(f"Archive contains no raw_slices JSONL files: {archive}")
        if not any(name.startswith(f"{prefix}project_status/") and name.endswith(".json") for name in names):
            raise RuntimeError(f"Archive contains no project_status JSON files: {archive}")
    return manifest


def _needed_for_merge(relative: PurePosixPath) -> bool:
    """Keep only completed-shard artifacts consumed by merge_shards.py."""
    return bool(relative.parts) and relative.parts[0] in RECOVERY_MEMBERS


def _archive_from_directory(source_dir: Path, destination: Path) -> Path:
    manifest_path = source_dir / "shard_manifest.json"
    manifest = _read_json(manifest_path.read_bytes(), str(manifest_path))
    validate_manifest(manifest, str(manifest_path))

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file() and not path.is_symlink():
                relative = path.relative_to(source_dir).as_posix()
                relative_path = PurePosixPath(relative)
                if _needed_for_merge(relative_path):
                    bundle.write(path, f"{SHARD_DIRECTORY}/{relative}")
    return destination


def _stage_existing_archive(source: Path, destination: Path) -> Path:
    """Rewrite a saved ZIP into a safe, duplicate-free shard archive."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as input_bundle:
        _, manifest_path = _valid_manifest_in_bundle(input_bundle, source)
        source_root = manifest_path.parent
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as output_bundle:
            copied = 0
            skipped_directories = 0
            skipped_symlinks = 0
            skipped_duplicates = 0
            skipped_unneeded = 0
            seen: dict[str, str] = {}
            for info in input_bundle.infolist():
                member = PurePosixPath(info.filename)
                try:
                    relative = member.relative_to(source_root)
                except ValueError:
                    continue
                if not relative.parts:
                    continue

                # Kaggle expands compressed files while processing a Dataset.
                # Explicit directory entries and archived symlinks can collide
                # with the real files below them (for example, "cy" and
                # "cy/..."), so only regular files are carried forward.
                if info.is_dir():
                    skipped_directories += 1
                    continue
                unix_mode = info.external_attr >> 16
                if stat.S_ISLNK(unix_mode):
                    skipped_symlinks += 1
                    continue

                if relative.is_absolute() or ".." in relative.parts:
                    raise RuntimeError(f"Unsafe member path in {source}: {info.filename!r}")
                if not _needed_for_merge(relative):
                    skipped_unneeded += 1
                    continue
                output_name = f"{SHARD_DIRECTORY}/{relative.as_posix()}"
                canonical = output_name.casefold()
                previous = seen.get(canonical)
                if previous is not None:
                    if previous == output_name:
                        skipped_duplicates += 1
                        continue
                    raise RuntimeError(
                        f"Case-insensitive path collision in {source}: "
                        f"{previous!r} and {output_name!r}"
                    )

                # Also reject a malformed archive that contains both a regular
                # file and descendants below that same path.
                parts = PurePosixPath(output_name).parts
                parents = {PurePosixPath(*parts[:index]).as_posix().casefold() for index in range(1, len(parts))}
                parent_file = next((seen[parent] for parent in parents if parent in seen), None)
                if parent_file is not None:
                    raise RuntimeError(
                        f"File/directory path collision in {source}: "
                        f"{parent_file!r} blocks {output_name!r}"
                    )
                child_file = next(
                    (name for key, name in seen.items() if key.startswith(canonical + "/")),
                    None,
                )
                if child_file is not None:
                    raise RuntimeError(
                        f"File/directory path collision in {source}: "
                        f"{output_name!r} blocks {child_file!r}"
                    )

                seen[canonical] = output_name
                with input_bundle.open(info) as input_file, output_bundle.open(output_name, "w") as output_file:
                    shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
                copied += 1
            if copied == 0:
                raise RuntimeError(f"No shard files could be copied from {source}")
            print(
                "Clean ZIP rewrite:",
                {
                    "files": copied,
                    "skipped_directories": skipped_directories,
                    "skipped_symlinks": skipped_symlinks,
                    "skipped_duplicates": skipped_duplicates,
                    "skipped_unneeded": skipped_unneeded,
                },
            )
    return destination


def _inventory(download_root: Path, archives: list[Path], manifests: list[Path]) -> str:
    try:
        top_level = sorted(download_root.iterdir())
    except OSError as exc:
        return f"could not list download root: {exc}"

    def describe(paths: list[Path], limit: int = 30) -> str:
        if not paths:
            return "(none)"
        rendered = []
        for path in paths[:limit]:
            try:
                size = f" ({path.stat().st_size} bytes)" if path.is_file() else "/"
            except OSError:
                size = ""
            rendered.append(f"{path.relative_to(download_root)}{size}")
        if len(paths) > limit:
            rendered.append(f"... and {len(paths) - limit} more")
        return ", ".join(rendered)

    return (
        f"top-level: {describe(top_level)}\n"
        f"ZIP files: {describe(archives)}\n"
        f"shard manifests: {describe(manifests)}"
    )


def find_or_build_archive(download_root: Path, staging_dir: Path) -> Path:
    """Copy the saved archive, or rebuild it from the saved working directory."""
    archives = sorted(download_root.rglob("*.zip"))
    valid_archives: list[Path] = []
    errors: list[str] = []
    for archive in archives:
        try:
            validate_archive(archive)
            valid_archives.append(archive)
        except RuntimeError as exc:
            errors.append(str(exc))

    staging_dir.mkdir(parents=True, exist_ok=True)
    staged_archive = staging_dir / SHARD_ARCHIVE
    if valid_archives:
        # Duplicate copies can exist under both the notebook output root and its
        # publish directory. Prefer the largest valid copy deterministically,
        # then normalize its internal top-level directory name.
        source = max(valid_archives, key=lambda item: (item.stat().st_size, str(item)))
        _stage_existing_archive(source, staged_archive)
        return staged_archive

    manifest_paths = sorted(download_root.rglob("shard_manifest.json"))
    for manifest_path in manifest_paths:
        shard_dir = manifest_path.parent
        try:
            archive = _archive_from_directory(shard_dir, staged_archive)
            validate_archive(archive)
            return archive
        except RuntimeError as exc:
            errors.append(str(exc))

    details = "\n- ".join(errors) if errors else "no matching archive or directory found"
    raise RuntimeError(
        f"Could not recover a valid {SHARD_ARCHIVE} from {download_root}:\n- {details}\n"
        f"Discovered output:\n{_inventory(download_root, archives, manifest_paths)}"
    )


def download_version_8(handle: str, destination: Path, reuse: bool) -> Path:
    try:
        import kagglehub
    except ImportError as exc:
        raise RuntimeError(
            "kagglehub is required. Run: pip install -U kagglehub"
        ) from exc

    if reuse and destination.exists() and any(destination.iterdir()):
        print(f"Reusing downloaded output: {destination}")
        return destination

    destination.mkdir(parents=True, exist_ok=True)
    print(f"Downloading exact notebook output: {handle}")
    result = kagglehub.notebook_output_download(
        handle,
        output_dir=str(destination),
        force_download=True,
    )
    result_path = Path(result) if result else destination
    if not result_path.exists():
        raise RuntimeError(f"kagglehub returned a missing output path: {result_path}")
    return result_path


def upload_dataset(handle: str, staging_dir: Path, version_notes: str) -> None:
    import kagglehub

    print(f"Uploading Dataset: {handle}")
    kagglehub.dataset_upload(
        handle,
        str(staging_dir),
        version_notes=version_notes,
    )


def main() -> int:
    args = parse_args()
    work_dir = args.work_dir.resolve()
    download_dir = work_dir / "notebook_output"
    staging_dir = work_dir / "dataset_payload"

    # The explicit /versions/8 suffix is a safety condition, not just a default.
    if not args.notebook.rstrip("/").endswith("/versions/8"):
        raise ValueError(
            "Refusing to continue: --notebook must explicitly end in /versions/8"
        )

    downloaded = download_version_8(args.notebook, download_dir, args.reuse_download)
    archive = find_or_build_archive(downloaded, staging_dir)
    manifest = validate_archive(archive)
    print(
        json.dumps(
            {
                "archive": str(archive),
                "archive_bytes": archive.stat().st_size,
                "shard_index": manifest["shard_index"],
                "shard_count": manifest["shard_count"],
                "selected_projects": manifest["selected_projects"],
                "attempted_projects": manifest["attempted_projects"],
                "failed_projects": manifest.get("failed_projects"),
                "exported_slices": manifest.get("exported_slices"),
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    if args.download_only:
        print("Validation succeeded; --download-only selected, so nothing was uploaded.")
        return 0

    upload_dataset(args.dataset, staging_dir, args.version_notes)
    print(
        "Dataset upload was accepted and is still being processed. "
        "It is not ready until `kaggle datasets status` reports a successful state."
    )
    print(f"Pending Dataset URL: https://www.kaggle.com/datasets/{args.dataset}")
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
    if exit_code:
        raise SystemExit(exit_code)
