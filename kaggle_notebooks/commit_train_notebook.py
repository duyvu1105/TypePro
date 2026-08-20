"""Render, push, or inspect the GPU training notebook on Kaggle."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from commit_shard_versions import load_credential, run_push


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
OWNER = "duyvu1105"
KERNEL_SLUG = "typepro-python-train-and-infer"
NOTEBOOK_PATH = ROOT / "12_train_and_infer.ipynb"
DATASET_SOURCES = ["duyvu1105/typepro-python-generative"]
CREDENTIAL_PATH = REPO_ROOT / "kaggle.json"


def kernel_metadata(code_file: str) -> dict:
    return {
        "id": f"{OWNER}/{KERNEL_SLUG}",
        "title": "TypePro Python Train & Infer",
        "code_file": code_file,
        "language": "python",
        "kernel_type": "notebook",
        "is_private": True,
        "enable_gpu": True,
        "enable_internet": True,
        "keywords": [],
        "dataset_sources": DATASET_SOURCES,
        "kernel_sources": [],
        "competition_sources": [],
        "model_sources": [],
    }


def write_payload(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    if not notebook.get("metadata", {}).get("kaggle", {}).get("isGpuEnabled"):
        raise RuntimeError("Training notebook must enable the GPU accelerator")
    serialized = json.dumps(notebook)
    if "typepro-codet5p-generative-project-kb-v1" not in serialized:
        raise RuntimeError("Training notebook is missing the generative Dataset schema marker")
    code_path = destination / "typepro_train_and_infer.ipynb"
    metadata_path = destination / "kernel-metadata.json"
    code_path.write_text(
        json.dumps(notebook, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    metadata_path.write_text(
        json.dumps(kernel_metadata(code_path.name), indent=2),
        encoding="utf-8",
    )
    json.loads(code_path.read_text(encoding="utf-8"))
    json.loads(metadata_path.read_text(encoding="utf-8"))


def kernel_status(credential: dict[str, str], config_dir: Path) -> str:
    environment = os.environ.copy()
    environment["KAGGLE_CONFIG_DIR"] = str(config_dir)
    environment["KAGGLE_USERNAME"] = credential["username"]
    environment["KAGGLE_KEY"] = credential["key"]
    environment.pop("KAGGLE_API_TOKEN", None)
    result = subprocess.run(
        ["kaggle", "kernels", "status", f"{OWNER}/{KERNEL_SLUG}"],
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = (result.stdout or "").strip()
    if result.returncode:
        raise RuntimeError(f"Cannot query training kernel: {output}")
    return output


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--check-status", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "typepro_kernel_versions" / "train_and_infer",
    )
    args = parser.parse_args(argv)
    if args.push and args.check_status:
        parser.error("--push and --check-status are mutually exclusive")

    credential = load_credential(CREDENTIAL_PATH, OWNER)
    if args.check_status:
        with tempfile.TemporaryDirectory(prefix="typepro_train_status_") as temp:
            status = kernel_status(credential, Path(temp))
        result = {"pushed": False, "status": status}
    elif args.push:
        with tempfile.TemporaryDirectory(prefix="typepro_train_push_") as temp:
            payload = Path(temp) / "payload"
            auth = Path(temp) / "auth"
            auth.mkdir()
            write_payload(payload)
            output = run_push(payload, credential, auth)
        result = {"pushed": True, "cli_output": output}
    else:
        destination = args.output_dir.resolve()
        write_payload(destination)
        result = {"pushed": False, "rendered_to": str(destination)}

    print(json.dumps({
        "kernel": f"{OWNER}/{KERNEL_SLUG}",
        "dataset_sources": DATASET_SOURCES,
        **result,
    }, indent=2))


if __name__ == "__main__":
    main()
