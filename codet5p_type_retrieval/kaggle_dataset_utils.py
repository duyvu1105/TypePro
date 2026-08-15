"""Validated Kaggle Dataset publishing shared by shard and final exporters."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path


OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,49}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,49}$")
MISSING_MARKERS = ("404", "not found", "could not find")
FORBIDDEN_MARKERS = ("403", "forbidden")
PUBLISH_ERROR_MARKERS = (
    "dataset creation error:",
    "dataset version creation error:",
)


def _has_word(value: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(word)}\b", value) for word in words)


def validate_dataset_id(dataset_id: str) -> tuple[str, str]:
    if not isinstance(dataset_id, str) or dataset_id.count("/") != 1:
        raise ValueError("Dataset id must be a non-null owner/dataset-slug string")
    owner, slug = (part.strip() for part in dataset_id.split("/", 1))
    if not OWNER_RE.fullmatch(owner):
        raise ValueError(f"Invalid or null Kaggle owner slug: {owner!r}")
    if not SLUG_RE.fullmatch(slug):
        raise ValueError(
            f"Invalid or null Kaggle dataset slug: {slug!r}; use 3-50 lowercase "
            "letters/digits/hyphens"
        )
    credential_owner = os.environ.get("KAGGLE_USERNAME", "").strip()
    if not credential_owner:
        raise RuntimeError("KAGGLE_USERNAME is missing or empty")
    if owner.casefold() != credential_owner.casefold():
        raise RuntimeError(
            f"Dataset owner {owner!r} does not match authenticated account "
            f"KAGGLE_USERNAME={credential_owner!r}"
        )
    if not os.environ.get("KAGGLE_KEY", "").strip():
        raise RuntimeError("KAGGLE_KEY is missing or empty")
    return owner, slug


def validate_title(title: str) -> str:
    title = title.strip()
    if not 6 <= len(title) <= 50:
        raise ValueError("Kaggle Dataset title must contain 6-50 characters")
    return title


def write_metadata(data_dir: Path, dataset_id: str, title: str) -> Path:
    validate_dataset_id(dataset_id)
    metadata = {
        "title": validate_title(title),
        "id": dataset_id,
        "licenses": [{"name": "CC-BY-4.0"}],
    }
    path = data_dir / "dataset-metadata.json"
    path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    # Read it back before invoking Kaggle so a truncated/invalid metadata file
    # cannot become an opaque server-side slug/hashlink error.
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if loaded != metadata:
        raise RuntimeError(f"Dataset metadata verification failed: {path}")
    return path


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command), flush=True)
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.stdout:
        print(result.stdout.rstrip(), flush=True)
    return result


def _raise_for_publish_error(
    result: subprocess.CompletedProcess[str],
    dataset_id: str,
    operation: str,
) -> None:
    output = (result.stdout or "").strip()
    lowered = output.casefold()
    semantic_error = any(marker in lowered for marker in PUBLISH_ERROR_MARKERS)
    if result.returncode or semantic_error:
        raise RuntimeError(
            f"Kaggle Dataset {operation} command failed for {dataset_id} "
            f"(exit {result.returncode}): {output}"
        )


def _status(dataset_id: str) -> tuple[str, str]:
    result = _run(["kaggle", "datasets", "status", dataset_id])
    output = (result.stdout or "").strip()
    lowered = output.casefold()
    if result.returncode:
        if any(marker in lowered for marker in MISSING_MARKERS):
            return "missing", output
        if any(marker in lowered for marker in FORBIDDEN_MARKERS):
            # Kaggle CLI 1.7.x can create a private Dataset successfully while
            # its legacy /datasets/status endpoint returns 403. Fall back to
            # file listing, which also proves that the uploaded payload exists.
            files_result = _run(
                ["kaggle", "datasets", "files", dataset_id, "--page-size", "10"]
            )
            files_output = (files_result.stdout or "").strip()
            files_lowered = files_output.casefold()
            if files_result.returncode == 0:
                return "ready", files_output
            if any(marker in files_lowered for marker in MISSING_MARKERS):
                return "missing", files_output
            if any(marker in files_lowered for marker in FORBIDDEN_MARKERS):
                return "pending", files_output
            raise RuntimeError(
                f"Cannot list Kaggle Dataset files for {dataset_id} "
                f"(exit {files_result.returncode}): {files_output}"
            )
        raise RuntimeError(
            f"Cannot query Kaggle Dataset status for {dataset_id} "
            f"(exit {result.returncode}): {output}"
        )
    if _has_word(lowered, ("error", "failed", "failure")):
        return "failed", output
    if _has_word(lowered, ("pending", "processing", "running", "creating")):
        return "pending", output
    if _has_word(lowered, ("ready", "complete", "successful", "success")):
        return "ready", output
    # A successful status lookup proves that the owner/slug exists even when a
    # newer CLI changes the human-readable state text.
    return "exists", output


def wait_for_status(
    dataset_id: str,
    *,
    timeout_seconds: int = 900,
    poll_seconds: int = 10,
    allow_initial_stale_failure: bool = False,
) -> str:
    started = time.monotonic()
    deadline = time.monotonic() + timeout_seconds
    last_state = "pending"
    while time.monotonic() < deadline:
        state, detail = _status(dataset_id)
        last_state = state
        if state in {"ready", "exists"}:
            return state
        if (
            state == "failed"
            and allow_initial_stale_failure
            and time.monotonic() - started < min(60, timeout_seconds)
        ):
            print(
                "Dataset still reports the previous failed version; waiting for the new version",
                flush=True,
            )
            time.sleep(poll_seconds)
            continue
        if state == "failed":
            raise RuntimeError(f"Kaggle Dataset processing failed: {detail}")
        print(f"Dataset state={state}; checking again in {poll_seconds}s", flush=True)
        time.sleep(poll_seconds)
    raise TimeoutError(
        f"Dataset {dataset_id} did not finish within {timeout_seconds}s; "
        f"last state={last_state}"
    )


def publish_dataset(
    data_dir: Path,
    dataset_id: str,
    title: str,
    message: str,
    *,
    public: bool = False,
) -> str:
    data_dir = data_dir.resolve()
    if not data_dir.is_dir():
        raise FileNotFoundError(data_dir)
    if shutil.which("kaggle") is None:
        raise RuntimeError("Install the Kaggle CLI first: pip install -U kaggle")
    validate_dataset_id(dataset_id)
    write_metadata(data_dir, dataset_id, title)
    payloads = [path for path in data_dir.iterdir() if path.name != "dataset-metadata.json"]
    if not payloads:
        raise RuntimeError(f"No Dataset payload files in {data_dir}")

    state, _ = _status(dataset_id)
    if state == "pending":
        wait_for_status(dataset_id)
        state, _ = _status(dataset_id)

    common = ["-p", str(data_dir), "--dir-mode", "skip"]
    if state == "missing":
        command = ["kaggle", "datasets", "create", *common]
        if public:
            command.append("--public")
        operation = "created"
    else:
        # This also repairs a Dataset whose first version exists but processing
        # failed: create a clean version rather than trying to recreate its slug.
        command = ["kaggle", "datasets", "version", *common, "-m", message]
        operation = "versioned"
    result = _run(command)
    # Kaggle CLI 2.2.4 can print a server-side creation error while returning
    # exit code 0, so checking only returncode would incorrectly report success.
    _raise_for_publish_error(result, dataset_id, operation)
    wait_for_status(dataset_id, allow_initial_stale_failure=True)
    url = f"https://www.kaggle.com/datasets/{dataset_id}"
    print(f"Dataset {operation} successfully: {url}", flush=True)
    return url
