"""Download and verify the final TypePro dataset produced by Cloud Run."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


DEFAULT_PROJECT = "project-7df9f963-9fe0-4b76-b3d"
DEFAULT_BUCKET = "project-7df9f963-9fe0-4b76-b3d-typepro"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download the completed TypePro Cloud Run dataset")
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--output-dir", default="typepro_python_contrastive")
    parser.add_argument("--run-id", help="Download a specific run instead of final/latest.json")
    return parser.parse_args()


def gcloud_cp(source: str, destination: Path, project: str) -> None:
    subprocess.run(
        ["gcloud", "storage", "cp", source, str(destination), "--project", project],
        check=True,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract(archive: Path, output_dir: Path) -> None:
    root = output_dir.resolve()
    with zipfile.ZipFile(archive) as handle:
        for member in handle.infolist():
            destination = (root / member.filename).resolve()
            if destination != root and root not in destination.parents:
                raise ValueError(f"Unsafe ZIP member: {member.filename}")
        handle.extractall(root)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="typepro-download-") as temporary:
        temp = Path(temporary)
        completion_path = temp / "completion.json"
        completion_uri = (
            f"gs://{args.bucket}/runs/{args.run_id}/final/completion.json"
            if args.run_id
            else f"gs://{args.bucket}/final/latest.json"
        )
        gcloud_cp(completion_uri, completion_path, args.project)
        completion = json.loads(completion_path.read_text(encoding="utf-8"))
        if completion.get("bucket") != args.bucket:
            raise ValueError(f"Completion manifest bucket mismatch: {completion.get('bucket')}")
        archive_info = completion["archive"]
        archive = temp / "typepro-python-contrastive.zip"
        gcloud_cp(archive_info["gcs_uri"], archive, args.project)
        actual = sha256(archive)
        if actual != archive_info["sha256"]:
            raise ValueError(f"Archive checksum mismatch: {actual} != {archive_info['sha256']}")
        safe_extract(archive, output_dir)
        shutil.copy2(completion_path, output_dir / "CLOUD_RUN_COMPLETION.json")
    print(f"Dataset downloaded and verified: {output_dir}")


if __name__ == "__main__":
    main()
