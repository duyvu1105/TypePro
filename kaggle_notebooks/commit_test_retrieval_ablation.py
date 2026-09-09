"""Render, push, or inspect the test-only retrieval ablation notebook."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from commit_shard_versions import load_credential, run_push


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
OWNER = "duyvu1105"
KERNEL_SLUG = "typepro-test-member-retrieval-ablation"
NOTEBOOK_PATH = ROOT / "14_test_retrieval_ablation.ipynb"
DATASET_SOURCES = ["duyvu1105/typepro-python-generative"]
CREDENTIAL_PATH = REPO_ROOT / "kaggle.json"
REVISION_MARKER = "__TYPEPRO_REVISION__"


def kernel_metadata(code_file: str) -> dict:
    return {
        "id": f"{OWNER}/{KERNEL_SLUG}",
        "title": "TypePro Test Member Retrieval Ablation",
        "code_file": code_file,
        "language": "python",
        "kernel_type": "notebook",
        "is_private": True,
        "enable_gpu": False,
        "enable_internet": True,
        "keywords": [],
        "dataset_sources": DATASET_SOURCES,
        "kernel_sources": [],
        "competition_sources": [],
        "model_sources": [],
    }


def resolve_revision(value: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", value], cwd=REPO_ROOT, check=True,
        text=True, stdout=subprocess.PIPE,
    ).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", result):
        raise RuntimeError(f"Expected a full Git revision, found {result!r}")
    return result


def write_payload(destination: Path, revision: str) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    serialized = json.dumps(notebook)
    if serialized.count(REVISION_MARKER) != 1:
        raise RuntimeError("Ablation notebook must contain exactly one revision marker")
    serialized = serialized.replace(REVISION_MARKER, revision)
    required = (
        "only-project-list", "target-member", "keyword-only",
        "comparison.json", "typepro-python-generative",
    )
    missing = [value for value in required if value.casefold() not in serialized.casefold()]
    if missing:
        raise RuntimeError(f"Ablation notebook is missing markers: {missing}")
    rendered = json.loads(serialized)
    code_path = destination / "typepro_test_retrieval_ablation.ipynb"
    code_path.write_text(json.dumps(rendered, ensure_ascii=False, indent=1), encoding="utf-8")
    (destination / "kernel-metadata.json").write_text(
        json.dumps(kernel_metadata(code_path.name), indent=2), encoding="utf-8"
    )


def kernel_status(credential: dict[str, str], config_dir: Path) -> str:
    environment = os.environ.copy()
    environment["KAGGLE_CONFIG_DIR"] = str(config_dir)
    environment["KAGGLE_USERNAME"] = credential["username"]
    environment["KAGGLE_KEY"] = credential["key"]
    environment.pop("KAGGLE_API_TOKEN", None)
    result = subprocess.run(
        ["kaggle", "kernels", "status", f"{OWNER}/{KERNEL_SLUG}"],
        env=environment, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode:
        raise RuntimeError(f"Cannot query ablation kernel: {(result.stdout or '').strip()}")
    return (result.stdout or "").strip()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--check-status", action="store_true")
    parser.add_argument(
        "--output-dir", type=Path,
        default=REPO_ROOT / "typepro_kernel_versions" / "test_retrieval_ablation",
    )
    args = parser.parse_args(argv)
    if args.push and args.check_status:
        parser.error("--push and --check-status are mutually exclusive")
    revision = resolve_revision(args.revision)
    credential = load_credential(CREDENTIAL_PATH, OWNER)
    if args.check_status:
        with tempfile.TemporaryDirectory(prefix="typepro_ablation_status_") as temp:
            result = {"pushed": False, "status": kernel_status(credential, Path(temp))}
    elif args.push:
        with tempfile.TemporaryDirectory(prefix="typepro_ablation_push_") as temp:
            payload = Path(temp) / "payload"
            auth = Path(temp) / "auth"
            auth.mkdir()
            write_payload(payload, revision)
            output = run_push(payload, credential, auth)
        result = {"pushed": True, "cli_output": output}
    else:
        destination = args.output_dir.resolve()
        write_payload(destination, revision)
        result = {"pushed": False, "rendered_to": str(destination)}
    print(json.dumps({
        "kernel": f"{OWNER}/{KERNEL_SLUG}",
        "revision": revision,
        "dataset_sources": DATASET_SOURCES,
        **result,
    }, indent=2))


if __name__ == "__main__":
    main()
