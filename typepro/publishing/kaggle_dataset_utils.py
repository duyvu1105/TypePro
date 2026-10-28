"""Validated Kaggle Dataset publishing shared by shard and final exporters."""

from __future__ import annotations


import csv
import io
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
STATUS_AUTH_MARKERS = (*FORBIDDEN_MARKERS, "401", "unauthorized")
PUBLISH_ERROR_MARKERS = (
    "dataset creation error:",
    "dataset version creation error:",
    "error during creation:",
)
RATE_LIMIT_MARKERS = ("429", "too many requests", "rate limit")


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
    # Do not require KAGGLE_KEY here. Kaggle notebooks can authenticate the
    # CLI with their host identity/access token and intentionally have no
    # legacy key in the environment. KAGGLE_USERNAME is still set by the
    # notebook as an explicit owner guard; the Kaggle API performs the actual
    # credential/permission check.
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


def _run_publish_with_retry(
    command: list[str],
    dataset_id: str,
    operation: str,
    previous_version: int,
    *,
    attempts: int = 6,
) -> subprocess.CompletedProcess[str]:
    """Retry a rejected Dataset mutation without creating duplicate versions."""
    for attempt in range(attempts):
        result = _run(command)
        output = (result.stdout or "").casefold()
        semantic_error = any(marker in output for marker in PUBLISH_ERROR_MARKERS)
        failed = bool(result.returncode or semantic_error)
        if not failed:
            return result
        if not any(marker in output for marker in RATE_LIMIT_MARKERS):
            _raise_for_publish_error(result, dataset_id, operation)
        # A proxy can return 429 after Kaggle accepted the mutation. Never
        # submit a second version until the exact owner listing proves that the
        # first request did not advance the Dataset.
        if _current_version(dataset_id) > previous_version:
            print(
                "Dataset version advanced despite the rate-limit response; "
                "continuing with status verification",
                flush=True,
            )
            return subprocess.CompletedProcess(command, 0, result.stdout, None)
        if attempt + 1 == attempts:
            _raise_for_publish_error(result, dataset_id, operation)
        delay = min(300, 30 * (2 ** attempt))
        print(
            f"Kaggle Dataset publish rate-limited; retrying in {delay}s "
            f"({attempt + 1}/{attempts})",
            flush=True,
        )
        time.sleep(delay)
    raise AssertionError("unreachable")


def _owned_dataset_exists(dataset_id: str) -> bool:
    """Return whether the exact Dataset ref appears in the owner's Datasets.

    Kaggle can return HTTP 403 for both a private Dataset that is still being
    registered and a Dataset slug that does not exist.  The authenticated
    owner's Dataset listing is therefore the existence check; status and file
    endpoints are only used after existence has been established.
    """
    slug = dataset_id.rsplit("/", 1)[-1]
    result = _run(
        [
            "kaggle",
            "datasets",
            "list",
            "--mine",
            "--search",
            slug,
            "--csv",
        ]
    )
    output = (result.stdout or "").strip()
    if result.returncode:
        raise RuntimeError(
            f"Cannot list Datasets owned by the authenticated Kaggle account "
            f"(exit {result.returncode}): {output}"
        )
    if not output or "no datasets found" in output.casefold():
        return False

    rows = list(csv.reader(io.StringIO(output)))
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if row and row[0].strip().casefold() in {"ref", "reference"}
        ),
        None,
    )
    if header_index is None:
        raise RuntimeError(
            "Cannot parse `kaggle datasets list --mine --csv` output; refusing "
            f"to guess whether {dataset_id} exists: {output}"
        )
    expected = dataset_id.casefold()
    return any(
        row and row[0].strip().casefold() == expected
        for row in rows[header_index + 1 :]
    )


def _status(dataset_id: str) -> tuple[str, str]:
    result = _run(["kaggle", "datasets", "status", dataset_id])
    output = (result.stdout or "").strip()
    lowered = output.casefold()
    if result.returncode:
        if any(marker in lowered for marker in MISSING_MARKERS):
            return "missing", output
        if any(marker in lowered for marker in STATUS_AUTH_MARKERS):
            # The legacy /datasets/status endpoint can return 401/403 even
            # after the authenticated owner's listing succeeds. Fall back to
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
                # This path is reached only after the owner listing proved the
                # Dataset exists, or after create/version was accepted.  In
                # those contexts a temporary 403 is safe to treat as pending.
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


def _current_version(dataset_id: str) -> int:
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    owner, slug = dataset_id.split("/", 1)
    for item in api.dataset_list(user=owner, search=slug):
        if item.ref.casefold() == dataset_id.casefold():
            return int(item.current_version_number or 0)
    return 0


def wait_for_status(
    dataset_id: str,
    *,
    timeout_seconds: int = 900,
    poll_seconds: int = 10,
    allow_initial_stale_failure: bool = False,
    newer_than: int | None = None,
) -> str:
    started = time.monotonic()
    deadline = time.monotonic() + timeout_seconds
    last_state = "pending"
    while time.monotonic() < deadline:
        state, detail = _status(dataset_id)
        last_state = state
        if state in {"ready", "exists"}:
            if newer_than is None or _current_version(dataset_id) > newer_than:
                return state
            print(f"Published version has not advanced beyond {newer_than}; waiting", flush=True)
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
    directory_mode: str = "skip",
) -> str:
    data_dir = data_dir.resolve()
    if not data_dir.is_dir():
        raise FileNotFoundError(data_dir)
    if shutil.which("kaggle") is None:
        raise RuntimeError("Install the Kaggle CLI first: pip install -U kaggle")
    validate_dataset_id(dataset_id)
    if directory_mode not in {"skip", "zip", "tar"}:
        raise ValueError(f"Unsupported Kaggle directory mode: {directory_mode}")
    write_metadata(data_dir, dataset_id, title)
    payloads = [path for path in data_dir.iterdir() if path.name != "dataset-metadata.json"]
    if not payloads:
        raise RuntimeError(f"No Dataset payload files in {data_dir}")

    dataset_exists = _owned_dataset_exists(dataset_id)
    state = "missing"
    if dataset_exists:
        state, _ = _status(dataset_id)
        if state == "missing":
            raise RuntimeError(
                f"Kaggle owner listing contains {dataset_id}, but its status/file "
                "endpoints report it missing; refusing to guess between create "
                "and version"
            )
        if state == "pending":
            wait_for_status(dataset_id)
            state, _ = _status(dataset_id)

    previous_version = _current_version(dataset_id) if dataset_exists else 0
    common = ["-p", str(data_dir), "--dir-mode", directory_mode]
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
    result = _run_publish_with_retry(
        command, dataset_id, operation, previous_version
    )
    # Kaggle CLI 2.2.4 can print a server-side creation error while returning
    # exit code 0, so checking only returncode would incorrectly report success.
    _raise_for_publish_error(result, dataset_id, operation)
    wait_for_status(
        dataset_id, allow_initial_stale_failure=True, newer_than=previous_version
    )
    url = f"https://www.kaggle.com/datasets/{dataset_id}"
    print(f"Dataset {operation} successfully: {url}", flush=True)
    return url
