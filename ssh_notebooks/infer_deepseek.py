"""Resumable DeepSeek type inference and exact-match evaluation for a JSONL test split."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import requests


REPO_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_DIR / "datasets/typepro-python-generative-v15/test.jsonl"
DEFAULT_OUTPUT_DIR = REPO_DIR / "outputs/deepseek-flash-v15"
API_URL = "https://api.deepseek.com/chat/completions"
PROMPT_VERSION = 1
SYSTEM_PROMPT = (
    "You are a Python type inference assistant. Infer the exact type annotation "
    "for the masked target using the code context and candidate definitions. "
    "Return only one Python type annotation. No explanation, Markdown, or quotes."
)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

sys.path.insert(0, str(REPO_DIR / "codet5p_type_retrieval"))
from type_labels import normalize_type_label  # noqa: E402


def load_api_key(env_file: Path) -> str:
    """Read only DEEPSEEK_API_KEY; never source .env as shell code or log its value."""
    value = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if value:
        return value
    if not env_file.is_file():
        raise RuntimeError(f"Missing DEEPSEEK_API_KEY and .env file: {env_file}")
    if env_file.stat().st_mode & 0o077:
        raise PermissionError(f"Credential file must have mode 600: {env_file}")
    for line in env_file.read_text(encoding="utf-8").splitlines():
        assignment = line.strip()
        if assignment.startswith("export "):
            assignment = assignment[7:].strip()
        if not assignment.startswith("DEEPSEEK_API_KEY="):
            continue
        value = assignment.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            return value
    raise RuntimeError("DEEPSEEK_API_KEY is missing or empty")


def iter_test_rows(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with path.open(encoding="utf-8") as handle:
        for position, line in enumerate(handle):
            row = json.loads(line)
            if not isinstance(row, dict) or not all(
                isinstance(row.get(field), str) and row[field]
                for field in ("id", "input", "label")
            ):
                raise ValueError(f"Invalid test row at line {position + 1}")
            yield position, row


def inspect_input(path: Path) -> tuple[str, dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    labels: dict[str, str] = {}
    for _, row in iter_test_rows(path):
        if row["id"] in labels:
            raise ValueError(f"Duplicate test ID: {row['id']}")
        labels[row["id"]] = normalize_type_label(row["label"])
    return digest.hexdigest(), labels


def config_for(args: argparse.Namespace, input_sha256: str) -> dict[str, Any]:
    return {
        "api_url": API_URL,
        "input_sha256": input_sha256,
        "model": args.model,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "thinking": "disabled",
        "prompt_version": PROMPT_VERSION,
    }


def open_checkpoint(path: Path, config: dict[str, Any]) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS run_config (name TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS predictions (
            id TEXT PRIMARY KEY,
            position INTEGER NOT NULL UNIQUE,
            label TEXT NOT NULL,
            prediction TEXT NOT NULL,
            normalized_prediction TEXT,
            exact_match INTEGER NOT NULL,
            raw_exact_match INTEGER NOT NULL,
            finish_reason TEXT NOT NULL,
            response_model TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER
        )"""
    )
    serialized = json.dumps(config, ensure_ascii=False, sort_keys=True)
    existing = connection.execute(
        "SELECT value FROM run_config WHERE name = 'config'"
    ).fetchone()
    if existing is None:
        if connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]:
            connection.close()
            raise ValueError("Checkpoint has predictions but no run configuration")
        connection.execute(
            "INSERT INTO run_config (name, value) VALUES ('config', ?)", (serialized,)
        )
        connection.commit()
    elif existing[0] != serialized:
        connection.close()
        raise ValueError(
            "Checkpoint belongs to another dataset/model/request configuration; "
            "choose another --output-dir"
        )
    return connection


@contextmanager
def exclusive_run_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another DeepSeek inference is using this output directory") from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def request_prediction(
    session: requests.Session,
    api_key: str,
    instruction: str,
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    max_retries: int,
) -> tuple[str, str, str | None, int | None, int | None]:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
        ],
        "thinking": {"type": "disabled"},
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for attempt in range(max_retries + 1):
        try:
            response = session.post(
                API_URL, headers=headers, json=body, timeout=(30, 660)
            )
        except (requests.Timeout, requests.ConnectionError) as error:
            if attempt == max_retries:
                raise RuntimeError(
                    f"DeepSeek connection failed after {attempt + 1} attempts "
                    f"({type(error).__name__})"
                ) from None
            delay = min(60, 2 ** attempt)
            print(f"Network retry {attempt + 1}/{max_retries}; wait {delay}s", flush=True)
            time.sleep(delay)
            continue
        if response.status_code in RETRYABLE_STATUS and attempt < max_retries:
            retry_after = response.headers.get("Retry-After", "")
            delay = float(retry_after) if retry_after.isdigit() else min(60, 2 ** attempt)
            print(
                f"DeepSeek HTTP {response.status_code}; retry {attempt + 1}/{max_retries} "
                f"after {delay:g}s",
                flush=True,
            )
            time.sleep(delay)
            continue
        if response.status_code != 200:
            raise RuntimeError(
                f"DeepSeek HTTP {response.status_code}; no prediction saved for this sample"
            )
        try:
            payload = response.json()
            choice = payload["choices"][0]
            prediction = choice["message"]["content"]
            finish_reason = choice["finish_reason"]
            if not isinstance(prediction, str) or finish_reason != "stop":
                raise ValueError(f"Incomplete completion: finish_reason={finish_reason!r}")
            usage = payload.get("usage") or {}
            return (
                prediction.strip(),
                finish_reason,
                payload.get("model"),
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
            )
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise RuntimeError(f"Invalid/incomplete DeepSeek response: {error}") from None
    raise AssertionError("Retry loop exited unexpectedly")


def save_prediction(
    connection: sqlite3.Connection,
    position: int,
    row: dict[str, Any],
    response: tuple[str, str, str | None, int | None, int | None],
) -> None:
    prediction, finish_reason, response_model, prompt_tokens, completion_tokens = response
    label = normalize_type_label(row["label"])
    try:
        normalized = normalize_type_label(prediction)
    except ValueError:
        normalized = None
    with connection:
        connection.execute(
            """INSERT INTO predictions (
                id, position, label, prediction, normalized_prediction,
                exact_match, raw_exact_match, finish_reason, response_model,
                prompt_tokens, completion_tokens
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["id"], position, label, prediction, normalized,
                int(normalized == label), int(prediction == row["label"]),
                finish_reason, response_model, prompt_tokens, completion_tokens,
            ),
        )


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def export_results(
    connection: sqlite3.Connection,
    labels: dict[str, str],
    output_dir: Path,
) -> dict[str, Any]:
    rows = connection.execute(
        """SELECT id, label, prediction, normalized_prediction, exact_match,
                  raw_exact_match, finish_reason, response_model,
                  prompt_tokens, completion_tokens
           FROM predictions ORDER BY position"""
    )
    predictions_path = output_dir / "test_predictions.jsonl"
    temporary = predictions_path.with_name(predictions_path.name + ".tmp")
    completed = correct = raw_correct = prompt_tokens = completion_tokens = 0
    with temporary.open("w", encoding="utf-8") as handle:
        for record in rows:
            (
                row_id, label, prediction, normalized, exact, raw_exact,
                finish_reason, response_model, prompt_used, completion_used,
            ) = record
            if row_id not in labels or label != labels[row_id]:
                raise ValueError(f"Checkpoint row does not match test input: {row_id}")
            completed += 1
            correct += exact
            raw_correct += raw_exact
            prompt_tokens += prompt_used or 0
            completion_tokens += completion_used or 0
            handle.write(json.dumps({
                "id": row_id,
                "prediction": prediction,
                "label": label,
                "normalized_prediction": normalized,
                "exact_match": bool(exact),
                "raw_exact_match": bool(raw_exact),
                "finish_reason": finish_reason,
                "response_model": response_model,
                "prompt_tokens": prompt_used,
                "completion_tokens": completion_used,
            }, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, predictions_path)
    total = len(labels)
    summary = {
        "status": "complete" if completed == total else "partial",
        "completed": completed,
        "total": total,
        "remaining": total - completed,
        "exact_matches": correct,
        "exact_match_accuracy_completed": correct / completed if completed else None,
        "exact_match_accuracy_full_test": correct / total if completed == total else None,
        "raw_exact_matches": raw_correct,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "predictions": str(predictions_path),
    }
    atomic_write_json(output_dir / "summary.json", summary)
    return summary


def run_inference(
    args: argparse.Namespace,
    *,
    session: requests.Session | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    input_sha256, labels = inspect_input(args.input)
    config = config_for(args, input_sha256)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.score_only:
        checkpoint = args.output_dir / "checkpoint.sqlite3"
        if not checkpoint.is_file():
            raise FileNotFoundError(checkpoint)
        connection = open_checkpoint(checkpoint, config)
        try:
            return export_results(connection, labels, args.output_dir)
        finally:
            connection.close()

    key = api_key if api_key is not None else load_api_key(args.env_file)
    owned_session = session is None
    if session is None:
        session = requests.Session()
    try:
        with exclusive_run_lock(args.output_dir / "checkpoint.lock"):
            connection = open_checkpoint(args.output_dir / "checkpoint.sqlite3", config)
            newly_completed = 0
            try:
                existing = connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
                print(
                    f"DeepSeek {args.model}: {existing}/{len(labels)} already checkpointed; "
                    f"input SHA-256 {input_sha256}",
                    flush=True,
                )
                for position, row in iter_test_rows(args.input):
                    saved = connection.execute(
                        "SELECT label, position FROM predictions WHERE id = ?", (row["id"],)
                    ).fetchone()
                    if saved is not None:
                        if saved != (labels[row["id"]], position):
                            raise ValueError(f"Checkpoint mismatch for ID: {row['id']}")
                        continue
                    if args.max_new is not None and newly_completed >= args.max_new:
                        break
                    response = request_prediction(
                        session, key, row["input"], model=args.model,
                        max_tokens=args.max_tokens, temperature=args.temperature,
                        max_retries=args.max_retries,
                    )
                    save_prediction(connection, position, row, response)
                    newly_completed += 1
                    if newly_completed % args.log_every == 0:
                        print(
                            f"Checkpointed {existing + newly_completed}/{len(labels)}; "
                            f"last ID: {row['id']}", flush=True,
                        )
            finally:
                summary = export_results(connection, labels, args.output_dir)
                connection.close()
                print(json.dumps(summary, ensure_ascii=False), flush=True)
            return summary
    finally:
        if owned_session:
            session.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--env-file", type=Path, default=REPO_DIR / ".env")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-retries", type=int, default=6)
    parser.add_argument("--max-new", type=int, help="Stop after this many NEW API calls")
    parser.add_argument("--log-every", type=int, default=25)
    parser.add_argument("--score-only", action="store_true", help="Export and score saved rows without API calls")
    args = parser.parse_args(argv)
    if args.max_tokens <= 0 or args.max_retries < 0 or args.log_every <= 0:
        parser.error("--max-tokens and --log-every must be positive; --max-retries must be nonnegative")
    if args.max_new is not None and args.max_new <= 0:
        parser.error("--max-new must be positive")
    if not 0 <= args.temperature <= 2:
        parser.error("--temperature must be between 0 and 2")
    return args


if __name__ == "__main__":
    run_inference(parse_args())
