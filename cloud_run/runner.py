"""Cloud Run entrypoints for building and finalizing the TypePro dataset.

Shard tasks use Cloud Run's task index and periodically checkpoint durable
files to Cloud Storage. The finalize task starts only after every shard task
has succeeded, downloads the ten verified builds, merges them, and uploads the
final dataset plus a ZIP archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable

from google.cloud import storage


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "codet5p_type_retrieval"
SHARD_COUNT = 10
SEED = 13
RETRIEVAL_SCHEMA_VERSION = "typepro-high-recall-v3"
TIMEOUT_PROJECTS = ("home-assistant/home-assistant", "Opentrons/opentrons")
CHECKPOINT_DIRECTORIES = ("metadata", "raw_slices", "project_status", "third_party_kb")
CHECKPOINT_FILES = ("runtime_manifest.json", "shard_manifest.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TypePro on Cloud Run Jobs")
    parser.add_argument("--mode", choices=("shard", "finalize"), required=True)
    parser.add_argument("--bucket", default=os.environ.get("TYPEPRO_BUCKET"))
    parser.add_argument("--run-id", default=os.environ.get("TYPEPRO_RUN_ID", "production-v1"))
    parser.add_argument("--checkpoint-seconds", type=int, default=300)
    parser.add_argument("--shard-count", type=int, default=SHARD_COUNT)
    parser.add_argument("--shard-index", type=int)
    args = parser.parse_args()
    if not args.bucket:
        parser.error("--bucket or TYPEPRO_BUCKET is required")
    if args.shard_count != SHARD_COUNT:
        parser.error(f"This deployment requires exactly {SHARD_COUNT} shards")
    if args.checkpoint_seconds < 30:
        parser.error("--checkpoint-seconds must be at least 30")
    return args


def run(command: Iterable[object], *, cwd: Path | None = None) -> None:
    printable = [str(value) for value in command]
    print("+", " ".join(printable), flush=True)
    subprocess.run(printable, cwd=cwd, check=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_object(name: str, prefix: str) -> Path:
    relative = PurePosixPath(name).relative_to(PurePosixPath(prefix))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe Cloud Storage object path: {name}")
    return Path(*relative.parts)


class GCSCheckpoint:
    def __init__(self, bucket: storage.Bucket, prefix: str, local_root: Path) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/") + "/"
        self.local_root = local_root
        self._fingerprints: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()

    def restore(self) -> int:
        count = 0
        for blob in self.bucket.list_blobs(prefix=self.prefix):
            if blob.name.endswith("/"):
                continue
            relative = safe_relative_object(blob.name, self.prefix)
            destination = self.local_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(destination)
            stat = destination.stat()
            self._fingerprints[relative.as_posix()] = (stat.st_size, stat.st_mtime_ns)
            count += 1
        print(f"Restored {count} checkpoint objects from gs://{self.bucket.name}/{self.prefix}", flush=True)
        return count

    def _paths(self) -> Iterable[Path]:
        for directory in CHECKPOINT_DIRECTORIES:
            root = self.local_root / directory
            if root.exists():
                yield from (path for path in root.rglob("*") if path.is_file())
        for filename in CHECKPOINT_FILES:
            path = self.local_root / filename
            if path.is_file():
                yield path

    def sync(self) -> int:
        uploaded = 0
        with self._lock:
            for path in self._paths():
                if path.name.endswith(".tmp"):
                    continue
                relative = path.relative_to(self.local_root).as_posix()
                stat = path.stat()
                fingerprint = (stat.st_size, stat.st_mtime_ns)
                if self._fingerprints.get(relative) == fingerprint:
                    continue
                self.bucket.blob(self.prefix + relative).upload_from_filename(path)
                self._fingerprints[relative] = fingerprint
                uploaded += 1
        if uploaded:
            print(f"Checkpoint uploaded {uploaded} changed files", flush=True)
        return uploaded


def validate_restored_schema(work_dir: Path) -> None:
    """Prevent a run ID from silently mixing retrieval implementations."""
    runtime_path = work_dir / "runtime_manifest.json"
    has_outputs = any((work_dir / name).exists() for name in ("raw_slices", "project_status"))
    if not runtime_path.exists():
        if has_outputs:
            raise ValueError(
                "Restored output has no runtime_manifest.json; deploy with a new TYPEPRO_RUN_ID"
            )
        return
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    actual = runtime.get("retrieval_schema_version")
    if actual != RETRIEVAL_SCHEMA_VERSION:
        raise ValueError(
            f"Restored retrieval schema {actual!r} != {RETRIEVAL_SCHEMA_VERSION!r}; "
            "deploy with a new TYPEPRO_RUN_ID"
        )


class PeriodicSync:
    def __init__(self, checkpoint: GCSCheckpoint, interval: int) -> None:
        self.checkpoint = checkpoint
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="gcs-checkpoint", daemon=True)

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            try:
                self.checkpoint.sync()
            except Exception as error:
                print(f"Checkpoint warning: {type(error).__name__}: {error}", file=sys.stderr, flush=True)

    def __enter__(self) -> "PeriodicSync":
        self.thread.start()
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.stop_event.set()
        self.thread.join(timeout=30)
        self.checkpoint.sync()


def selected_project_summary(work_dir: Path, shard_index: int, shard_count: int) -> dict[str, object]:
    sys.path.insert(0, str(PIPELINE))
    from prepare_dataset import project_from_row, read_json, stable_number

    projects = set()
    for split in ("train", "validation", "test"):
        for row in read_json(work_dir / "metadata" / f"{split}.json"):
            projects.add(project_from_row(row))
    selected = {
        project
        for project in projects
        if stable_number(project, SEED + 4) % shard_count == shard_index
    }
    statuses = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (work_dir / "project_status").glob("*.json")
    ]
    attempted = {item.get("project") for item in statuses}
    return {
        "shard_index": shard_index,
        "shard_count": shard_count,
        "retrieval_schema_version": RETRIEVAL_SCHEMA_VERSION,
        "selected_projects": len(selected),
        "attempted_projects": len(selected & attempted),
        "successful_projects": sum(item.get("project") in selected and "error" not in item for item in statuses),
        "failed_projects": sum(item.get("project") in selected and "error" in item for item in statuses),
        "exported_slices": sum(int(item.get("exported", 0)) for item in statuses if item.get("project") in selected),
        "missing_projects": sorted(selected - attempted),
        "completed_at": utc_now(),
    }


def shard_index_from_environment(explicit: int | None, shard_count: int) -> int:
    value = explicit if explicit is not None else int(os.environ.get("CLOUD_RUN_TASK_INDEX", "-1"))
    task_count = int(os.environ.get("CLOUD_RUN_TASK_COUNT", str(shard_count)))
    if task_count != shard_count:
        raise ValueError(f"CLOUD_RUN_TASK_COUNT={task_count}, expected {shard_count}")
    if not 0 <= value < shard_count:
        raise ValueError(f"Invalid shard index {value} for {shard_count} shards")
    return value


def run_shard(args: argparse.Namespace, client: storage.Client) -> None:
    shard_index = shard_index_from_environment(args.shard_index, args.shard_count)
    local_root = Path("/tmp/typepro")
    work_dir = local_root / f"shard_{shard_index:02d}"
    work_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = GCSCheckpoint(
        client.bucket(args.bucket),
        f"runs/{args.run_id}/shards/{shard_index:02d}/work",
        work_dir,
    )
    checkpoint.restore()
    validate_restored_schema(work_dir)
    prepare = PIPELINE / "prepare_dataset.py"
    common = [
        "--typepro-root", ROOT,
        "--work-dir", work_dir,
        "--split-profile", "paper_project",
        "--test-projects", 100,
        "--validation-project-ratio", 0.10,
        "--seed", SEED,
        "--preview-samples", 1,
        "--preview-max-chars", 1200,
    ]

    stopping = False
    original_sigterm = signal.getsignal(signal.SIGTERM)

    def handle_sigterm(_signum, _frame):
        nonlocal stopping
        stopping = True
        print("SIGTERM received; flushing checkpoint", flush=True)
        checkpoint.sync()
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, handle_sigterm)
    try:
        run([sys.executable, "-u", prepare, "--stage", "metadata", *common])
        checkpoint.sync()
        slice_command: list[object] = [
            sys.executable, "-u", prepare, "--stage", "slice", *common,
            "--shard-count", args.shard_count,
            "--shard-index", shard_index,
            "--slice-log-every", 100,
            "--slice-annotation-timeout-seconds", 600,
            "--retrieval-schema-version", RETRIEVAL_SCHEMA_VERSION,
            "--build-import-kb",
            "--download-missing-imports",
            "--kb-max-files-per-package", 3000,
        ]
        for project in TIMEOUT_PROJECTS:
            slice_command.extend(("--slice-timeout-project", project))
        with PeriodicSync(checkpoint, args.checkpoint_seconds):
            run(slice_command)
        summary = selected_project_summary(work_dir, shard_index, args.shard_count)
        write_json(work_dir / "shard_manifest.json", summary)
        checkpoint.sync()
        if summary["missing_projects"]:
            raise RuntimeError(f"Shard {shard_index:02d} has missing projects")
        print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    finally:
        if not stopping:
            signal.signal(signal.SIGTERM, original_sigterm)


def download_prefix(bucket: storage.Bucket, prefix: str, destination: Path) -> int:
    normalized = prefix.strip("/") + "/"
    count = 0
    for blob in bucket.list_blobs(prefix=normalized):
        if blob.name.endswith("/"):
            continue
        relative = safe_relative_object(blob.name, normalized)
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(path)
        count += 1
    return count


def create_zip(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())


def run_finalize(args: argparse.Namespace, client: storage.Client) -> None:
    bucket = client.bucket(args.bucket)
    root = Path("/tmp/typepro-finalize")
    shards_root = root / "shards"
    shard_dirs = []
    for shard_index in range(args.shard_count):
        shard_dir = shards_root / f"{shard_index:02d}"
        count = download_prefix(
            bucket,
            f"runs/{args.run_id}/shards/{shard_index:02d}/work",
            shard_dir,
        )
        marker_path = shard_dir / "shard_manifest.json"
        if not marker_path.exists():
            raise FileNotFoundError(f"Shard {shard_index:02d} has no manifest ({count} objects downloaded)")
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        expected = (shard_index, args.shard_count, RETRIEVAL_SCHEMA_VERSION)
        actual = (
            marker.get("shard_index"),
            marker.get("shard_count"),
            marker.get("retrieval_schema_version"),
        )
        if actual != expected or marker.get("missing_projects"):
            raise ValueError(f"Invalid shard manifest {shard_index:02d}: {marker}")
        shard_dirs.append(shard_dir)

    merged = root / "merged"
    final_dir = root / "typepro_python_contrastive"
    run([
        sys.executable, "-u", PIPELINE / "merge_shards.py",
        "--shard-build-dirs", *shard_dirs,
        "--work-dir", merged,
    ])
    run([
        sys.executable, "-u", PIPELINE / "prepare_dataset.py",
        "--stage", "finalize",
        "--typepro-root", ROOT,
        "--work-dir", merged,
        "--output-dir", final_dir,
        "--split-profile", "paper_project",
        "--test-projects", 100,
        "--validation-project-ratio", 0.10,
        "--max-negatives", 7,
        "--seed", SEED,
        "--preview-samples", 2,
        "--preview-max-chars", 1600,
        "--log-every", 10000,
    ])
    run([sys.executable, PIPELINE / "verify_dataset.py", "--data-dir", final_dir])

    completion = {
        "project_id": client.project,
        "bucket": args.bucket,
        "run_id": args.run_id,
        "shard_count": args.shard_count,
        "retrieval_schema_version": RETRIEVAL_SCHEMA_VERSION,
        "completed_at": utc_now(),
        "files": {},
    }
    final_prefix = f"runs/{args.run_id}/final/files"
    for path in sorted(final_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(final_dir).as_posix()
        bucket.blob(f"{final_prefix}/{relative}").upload_from_filename(path)
        completion["files"][relative] = {"bytes": path.stat().st_size, "sha256": sha256(path)}

    archive = root / "typepro-python-contrastive.zip"
    create_zip(final_dir, archive)
    archive_name = f"runs/{args.run_id}/final/typepro-python-contrastive.zip"
    bucket.blob(archive_name).upload_from_filename(archive)
    completion["archive"] = {
        "gcs_uri": f"gs://{args.bucket}/{archive_name}",
        "bytes": archive.stat().st_size,
        "sha256": sha256(archive),
    }
    completion_path = root / "completion.json"
    write_json(completion_path, completion)
    bucket.blob(f"runs/{args.run_id}/final/completion.json").upload_from_filename(completion_path)
    bucket.blob("final/latest.json").upload_from_filename(completion_path)
    print(json.dumps(completion, indent=2, ensure_ascii=False), flush=True)


def main() -> None:
    args = parse_args()
    client = storage.Client()
    if args.mode == "shard":
        run_shard(args, client)
    else:
        run_finalize(args, client)


if __name__ == "__main__":
    main()
