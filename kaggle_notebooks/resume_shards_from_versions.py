"""Resume interrupted TypePro shards from exact Kaggle notebook versions.

The historical outputs are mapped as follows:

* notebook version 6  -> shard 00
* notebook version 7  -> shard 01
* notebook version 10 -> shard 04

Run one shard per Kaggle session, for example::

    %pip install -q -U kagglehub
    !python /kaggle/input/<typepro-source>/kaggle_notebooks/resume_shards_from_versions.py --shard-index 0

The restored ``raw_slices``/``project_status`` pairs are left in
``/kaggle/working/typepro_build_shard_XX``.  ``prepare_dataset.py`` skips those
pairs and processes only unfinished projects.  The final upload contains only
the files consumed by the merge step; the build-time ``third_party_kb`` cache
is deliberately excluded.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


NOTEBOOK_OWNER = "duyvu1105"
NOTEBOOK_SLUG = "create-dataset"
DATASET_OWNER = "duyvu1105"
SHARD_COUNT = 5
VERSION_BY_SHARD = {0: 6, 1: 7, 4: 10}
RECOVERY_MEMBERS = {
    "metadata",
    "project_status",
    "raw_slices",
    "runtime_manifest.json",
    "shard_manifest.json",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resume TypePro shards 00, 01, or 04 from saved notebook output."
    )
    parser.add_argument(
        "--shard-index",
        type=int,
        required=True,
        choices=sorted(VERSION_BY_SHARD),
        help="Shard to resume: 0 (version 6), 1 (version 7), or 4 (version 10).",
    )
    parser.add_argument(
        "--notebook",
        help="Override the historical output handle; it must end in /versions/N.",
    )
    parser.add_argument(
        "--repository",
        default="https://github.com/duyvu1105/TypePro.git",
    )
    parser.add_argument("--branch", default="main")
    parser.add_argument(
        "--typepro-root",
        type=Path,
        help="Use an existing TypePro checkout instead of cloning it.",
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        default=Path("/kaggle/working"),
    )
    parser.add_argument(
        "--reuse-download",
        action="store_true",
        help="Reuse an already downloaded historical output.",
    )
    parser.add_argument(
        "--restore-only",
        action="store_true",
        help="Restore and validate progress, but do not resume the builder or upload.",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Resume and package the shard without uploading a Kaggle Dataset.",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Do not install requirements-build.txt before resuming.",
    )
    args, unknown = parser.parse_known_args(argv)

    # IPython kernels add ``-f <connection.json>`` when a file is executed with
    # %run or pasted into a notebook cell.
    remaining = list(unknown)
    while "-f" in remaining:
        index = remaining.index("-f")
        if index + 1 >= len(remaining):
            parser.error("argument -f: expected a Jupyter connection file")
        del remaining[index : index + 2]
    if remaining:
        parser.error(f"unrecognized arguments: {' '.join(remaining)}")
    return args


def run(command: list[object], cwd: Path | None = None) -> None:
    rendered = [str(value) for value in command]
    print("+", " ".join(rendered), flush=True)
    subprocess.run(rendered, cwd=cwd, check=True)


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected a JSON object in {path}")
    return value


def notebook_handle(args: argparse.Namespace) -> str:
    version = VERSION_BY_SHARD[args.shard_index]
    handle = args.notebook or (
        f"{NOTEBOOK_OWNER}/{NOTEBOOK_SLUG}/versions/{version}"
    )
    parts = handle.rstrip("/").split("/")
    if len(parts) < 4 or parts[-2] != "versions" or not parts[-1].isdigit():
        raise ValueError("--notebook must explicitly end in /versions/N")
    return handle


def download_output(handle: str, destination: Path, reuse: bool) -> Path:
    try:
        import kagglehub
    except ImportError as exc:
        raise RuntimeError("Install kagglehub first: pip install -U kagglehub") from exc

    if reuse and destination.exists() and any(destination.iterdir()):
        print("Reusing historical output:", destination)
        return destination
    destination.mkdir(parents=True, exist_ok=True)
    print("Downloading exact notebook output:", handle, flush=True)
    result = kagglehub.notebook_output_download(
        handle,
        output_dir=str(destination),
        force_download=True,
    )
    result_path = Path(result) if result else destination
    if not result_path.exists():
        raise RuntimeError(f"kagglehub returned a missing path: {result_path}")
    return result_path


def useful_existing_work(work_dir: Path) -> bool:
    return (
        (work_dir / "metadata" / "split_manifest.json").exists()
        or any((work_dir / "raw_slices").glob("*.jsonl"))
        or any((work_dir / "project_status").glob("*.json"))
    )


def _copy_recovery_tree(source: Path, destination: Path) -> int:
    copied = 0
    destination.mkdir(parents=True, exist_ok=True)
    for name in sorted(RECOVERY_MEMBERS):
        item = source / name
        target = destination / name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
            copied += sum(path.is_file() for path in item.rglob("*"))
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            copied += 1
    return copied


def _zip_root(bundle: zipfile.ZipFile, expected_name: str) -> PurePosixPath | None:
    for info in bundle.infolist():
        parts = PurePosixPath(info.filename).parts
        if expected_name in parts:
            return PurePosixPath(*parts[: parts.index(expected_name) + 1])
    return None


def _extract_recovery_zip(
    archive: Path,
    destination: Path,
    expected_name: str,
) -> int:
    copied = 0
    seen: set[str] = set()
    with zipfile.ZipFile(archive) as bundle:
        root = _zip_root(bundle, expected_name)
        if root is None and archive.stem != expected_name:
            return 0
        for info in bundle.infolist():
            if info.is_dir():
                continue
            unix_mode = info.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                continue
            member = PurePosixPath(info.filename)
            if root is not None:
                try:
                    relative = member.relative_to(root)
                except ValueError:
                    continue
            else:
                relative = member
            if (
                not relative.parts
                or relative.parts[0] not in RECOVERY_MEMBERS
                or relative.is_absolute()
                or ".." in relative.parts
            ):
                continue
            canonical = relative.as_posix().casefold()
            if canonical in seen:
                continue
            seen.add(canonical)
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source_file, target.open("wb") as target_file:
                shutil.copyfileobj(source_file, target_file, length=1024 * 1024)
            copied += 1
    return copied


def _recovery_zip_file_count(archive: Path, expected_name: str) -> int:
    with zipfile.ZipFile(archive) as bundle:
        root = _zip_root(bundle, expected_name)
        if root is None and archive.stem != expected_name:
            return 0
        count = 0
        for info in bundle.infolist():
            if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                continue
            member = PurePosixPath(info.filename)
            if root is not None:
                try:
                    relative = member.relative_to(root)
                except ValueError:
                    continue
            else:
                relative = member
            if relative.parts and relative.parts[0] in RECOVERY_MEMBERS:
                count += 1
        return count


def restore_progress(output_root: Path, work_dir: Path, shard_index: int) -> None:
    if useful_existing_work(work_dir):
        print("Using existing working state (historical output is not recopied):", work_dir)
        return

    expected_name = f"typepro_build_shard_{shard_index:02d}"
    directories = sorted(
        path for path in output_root.rglob(expected_name) if path.is_dir()
    )
    if output_root.name == expected_name and output_root.is_dir():
        directories.insert(0, output_root)
    if directories:
        source = max(
            directories,
            key=lambda path: (
                len(list((path / "project_status").glob("*.json"))),
                len(list((path / "raw_slices").glob("*.jsonl"))),
                str(path),
            ),
        )
        copied = _copy_recovery_tree(source, work_dir)
        if copied:
            print(f"Restored {copied} files from directory: {source}")
            return

    archives = sorted(output_root.rglob("*.zip"))
    archive_counts = [
        (_recovery_zip_file_count(archive, expected_name), archive)
        for archive in archives
        if zipfile.is_zipfile(archive)
    ]
    archive_counts = [item for item in archive_counts if item[0]]
    if archive_counts:
        _, archive = max(archive_counts, key=lambda item: (item[0], str(item[1])))
        count = _extract_recovery_zip(archive, work_dir, expected_name)
        print(f"Restored {count} files from archive: {archive}")
        return

    inventory = [str(path.relative_to(output_root)) for path in sorted(output_root.iterdir())]
    raise RuntimeError(
        f"No saved {expected_name} directory/archive found in {output_root}. "
        f"Top-level output: {inventory[:30]}"
    )


def ensure_checkout(args: argparse.Namespace, work_root: Path) -> Path:
    if args.typepro_root:
        root = args.typepro_root.resolve()
    else:
        root = work_root / "TypePro"
        if not root.exists():
            run([
                "git",
                "clone",
                "--branch",
                args.branch,
                "--single-branch",
                args.repository,
                root,
            ])
    prepare = root / "codet5p_type_retrieval" / "prepare_dataset.py"
    if not prepare.is_file() or not (root / "Python").is_dir():
        raise RuntimeError(f"Not a usable TypePro checkout: {root}")
    return root


def load_pipeline_helpers(typepro_root: Path) -> tuple[Any, Any, Any]:
    pipeline_dir = typepro_root / "codet5p_type_retrieval"
    sys.path.insert(0, str(pipeline_dir))
    from prepare_dataset import project_from_row, read_json, stable_number

    return project_from_row, read_json, stable_number


def selected_projects(typepro_root: Path, work_dir: Path, shard_index: int) -> set[str]:
    project_from_row, read_json, stable_number = load_pipeline_helpers(typepro_root)
    projects: set[str] = set()
    for split in ("train", "validation", "test"):
        for row in read_json(work_dir / "metadata" / f"{split}.json"):
            projects.add(project_from_row(row))
    return {
        project
        for project in projects
        if stable_number(project, 13 + 4) % SHARD_COUNT == shard_index
    }


def validate_restored_progress(
    typepro_root: Path,
    work_dir: Path,
    shard_index: int,
) -> dict[str, int]:
    selected = selected_projects(typepro_root, work_dir, shard_index)
    selected_slugs = {project.replace("/", "__") for project in selected}
    status_paths = sorted((work_dir / "project_status").glob("*.json"))
    raw_paths = sorted((work_dir / "raw_slices").glob("*.jsonl"))
    statuses = [read_object(path) for path in status_paths]
    foreign_statuses = sorted(
        str(item.get("project"))
        for item in statuses
        if item.get("project") not in selected
    )
    foreign_raw = sorted(path.name for path in raw_paths if path.stem not in selected_slugs)
    if foreign_statuses or foreign_raw:
        raise RuntimeError(
            "Historical output does not belong exclusively to the requested shard: "
            f"foreign_statuses={foreign_statuses[:10]}, foreign_raw={foreign_raw[:10]}"
        )

    # A previous failed status plus a newly written raw file can occur if the
    # kernel stops between os.replace(raw) and writing the success status.
    # Removing that unverified raw file makes prepare_dataset retry it safely.
    retried_uncertain = 0
    for path, status in zip(status_paths, statuses):
        if "error" in status:
            raw_path = work_dir / "raw_slices" / f"{path.stem}.jsonl"
            if raw_path.exists():
                raw_path.unlink()
                retried_uncertain += 1

    complete = sum(
        (work_dir / "raw_slices" / f"{path.stem}.jsonl").exists()
        and "error" not in status
        for path, status in zip(status_paths, statuses)
    )
    summary = {
        "selected_projects": len(selected),
        "saved_statuses": len(status_paths),
        "saved_raw_slices": len(raw_paths),
        "verified_complete_pairs": complete,
        "uncertain_pairs_scheduled_for_retry": retried_uncertain,
        "remaining_before_resume": len(selected) - complete,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def common_builder_args(typepro_root: Path, work_dir: Path) -> list[object]:
    return [
        "--typepro-root",
        typepro_root,
        "--work-dir",
        work_dir,
        "--split-profile",
        "paper_project",
        "--test-projects",
        100,
        "--validation-project-ratio",
        0.10,
        "--seed",
        13,
        "--preview-samples",
        1,
        "--preview-max-chars",
        1200,
    ]


def resume_builder(
    args: argparse.Namespace,
    typepro_root: Path,
    work_dir: Path,
) -> dict[str, Any]:
    pipeline_dir = typepro_root / "codet5p_type_retrieval"
    prepare = pipeline_dir / "prepare_dataset.py"
    if not args.skip_install:
        run([
            sys.executable,
            "-m",
            "pip",
            "install",
            "-q",
            "-r",
            pipeline_dir / "requirements-build.txt",
        ])
    common = common_builder_args(typepro_root, work_dir)
    run([
        sys.executable,
        "-u",
        prepare,
        "--stage",
        "slice",
        *common,
        "--shard-count",
        SHARD_COUNT,
        "--shard-index",
        args.shard_index,
        "--slice-log-every",
        50,
        "--build-import-kb",
        "--download-missing-imports",
        "--kb-max-files-per-package",
        3000,
    ])
    return write_completed_manifest(typepro_root, work_dir, args.shard_index)


def write_completed_manifest(
    typepro_root: Path,
    work_dir: Path,
    shard_index: int,
) -> dict[str, Any]:
    selected = selected_projects(typepro_root, work_dir, shard_index)
    statuses = [
        read_object(path)
        for path in sorted((work_dir / "project_status").glob("*.json"))
    ]
    attempted = {item.get("project") for item in statuses}
    missing = sorted(selected - attempted)
    successful = [
        item for item in statuses if item.get("project") in selected and "error" not in item
    ]
    absent_raw = sorted(
        str(item["project"])
        for item in successful
        if not (
            work_dir
            / "raw_slices"
            / f"{str(item['project']).replace('/', '__')}.jsonl"
        ).exists()
    )
    if absent_raw:
        raise RuntimeError(f"Successful statuses without raw slices: {absent_raw[:20]}")
    manifest = {
        "shard_index": shard_index,
        "shard_count": SHARD_COUNT,
        "selected_projects": len(selected),
        "attempted_projects": len(selected & attempted),
        "successful_projects": len(successful),
        "failed_projects": sum(
            item.get("project") in selected and "error" in item for item in statuses
        ),
        "exported_slices": sum(int(item.get("exported", 0)) for item in successful),
        "missing_projects": missing,
    }
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    (work_dir / "shard_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if missing:
        raise RuntimeError(f"Shard is incomplete: {len(missing)} projects missing")
    return manifest


def needed_for_merge(relative: PurePosixPath) -> bool:
    if not relative.parts:
        return False
    if relative.parts[0] == "raw_slices":
        return relative.suffix == ".jsonl"
    if relative.parts[0] == "project_status":
        return relative.suffix == ".json"
    return relative.parts[0] in {
        "metadata",
        "runtime_manifest.json",
        "shard_manifest.json",
    }


def package_shard(work_dir: Path, payload_dir: Path, shard_index: int) -> Path:
    directory_name = f"typepro_build_shard_{shard_index:02d}"
    archive = payload_dir / f"{directory_name}.zip"
    payload_dir.mkdir(parents=True, exist_ok=True)
    seen: dict[str, str] = {}
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(work_dir.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = PurePosixPath(path.relative_to(work_dir).as_posix())
            if not needed_for_merge(relative):
                continue
            output_name = f"{directory_name}/{relative.as_posix()}"
            canonical = output_name.casefold()
            previous = seen.get(canonical)
            if previous is not None:
                raise RuntimeError(
                    f"Case-insensitive archive collision: {previous!r} and {output_name!r}"
                )
            seen[canonical] = output_name
            bundle.write(path, output_name)
    if not seen:
        raise RuntimeError(f"No merge files found under {work_dir}")
    print("Packaged:", archive, f"({archive.stat().st_size} bytes)")
    return archive


def upload_shard(payload_dir: Path, shard_index: int, source_handle: str) -> None:
    import kagglehub

    dataset = f"{DATASET_OWNER}/typepro-build-shard-{shard_index:02d}"
    print("Uploading Dataset:", dataset, flush=True)
    kagglehub.dataset_upload(
        dataset,
        str(payload_dir),
        version_notes=f"Resume shard {shard_index:02d} from {source_handle}",
    )
    print(
        "Upload accepted and processing may still be pending. Check the Dataset status:",
        f"https://www.kaggle.com/datasets/{dataset}",
    )


def load_kaggle_secrets_if_available() -> None:
    if os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"):
        return
    try:
        from kaggle_secrets import UserSecretsClient

        secrets = UserSecretsClient()
        os.environ.setdefault("KAGGLE_USERNAME", secrets.get_secret("KAGGLE_USERNAME"))
        os.environ.setdefault("KAGGLE_KEY", secrets.get_secret("KAGGLE_KEY"))
    except Exception:
        # kagglehub can also use Kaggle's notebook environment authentication.
        pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_kaggle_secrets_if_available()
    handle = notebook_handle(args)
    work_root = args.work_root.resolve()
    work_dir = work_root / f"typepro_build_shard_{args.shard_index:02d}"
    download_dir = (
        work_root
        / "typepro_resume_sources"
        / f"version_{handle.rstrip('/').split('/')[-1]}"
    )
    output_root = download_output(handle, download_dir, args.reuse_download)
    restore_progress(output_root, work_dir, args.shard_index)

    typepro_root = ensure_checkout(args, work_root)
    prepare = typepro_root / "codet5p_type_retrieval" / "prepare_dataset.py"
    if not args.skip_install:
        # Restore-only validation imports prepare_dataset, whose tqdm dependency
        # may not be present in a non-Kaggle environment.
        run([
            sys.executable,
            "-m",
            "pip",
            "install",
            "-q",
            "-r",
            prepare.parent / "requirements-build.txt",
        ])
        args.skip_install = True
    common = common_builder_args(typepro_root, work_dir)
    run([sys.executable, "-u", prepare, "--stage", "metadata", *common])
    restored = validate_restored_progress(
        typepro_root,
        work_dir,
        args.shard_index,
    )
    if args.restore_only:
        print("Restore-only complete; projects still to run:", restored["remaining_before_resume"])
        return 0

    manifest = resume_builder(args, typepro_root, work_dir)
    payload_dir = work_root / f"publish_resume_shard_{args.shard_index:02d}"
    archive = package_shard(work_dir, payload_dir, args.shard_index)
    print(
        json.dumps(
            {
                "archive": str(archive),
                "archive_bytes": archive.stat().st_size,
                **manifest,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    if args.no_upload:
        print("--no-upload selected; the completed archive was not uploaded.")
        return 0
    upload_shard(payload_dir, args.shard_index, handle)
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
    # Avoid an unnecessary SystemExit: 0 traceback/warning when run in IPython.
    if exit_code:
        raise SystemExit(exit_code)
