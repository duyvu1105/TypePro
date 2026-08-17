"""Render, push, or inspect the final merge notebook under its Dataset owner."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from commit_shard_versions import load_credential, run_push


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
OWNER = "duyvu1105"
KERNEL_SLUG = "typepro-merge-finalize"
NOTEBOOK_PATH = ROOT / "03_merge_finalize.ipynb"
MERGE_PLAN_PATH = ROOT / "shard_merge_plan.json"
CREDENTIAL_PATH = REPO_ROOT / "kaggle.json"


def merge_dataset_ids() -> list[str]:
    plan = json.loads(MERGE_PLAN_PATH.read_text(encoding="utf-8"))
    if plan.get("final_dataset_owner") != OWNER:
        raise RuntimeError("Merge plan final owner does not match merge kernel owner")
    datasets = plan.get("datasets")
    if not isinstance(datasets, list) or len(datasets) != 16:
        raise RuntimeError("Merge plan must contain exactly 16 physical Datasets")
    result = [item["dataset_id"] for item in datasets]
    if len(result) != len(set(result)):
        raise RuntimeError("Merge plan contains duplicate Dataset IDs")
    return result


def kernel_metadata(code_file: str) -> dict:
    return {
        "id": f"{OWNER}/{KERNEL_SLUG}",
        "title": "TypePro Merge 16 Verified Partitions",
        "code_file": code_file,
        "language": "python",
        "kernel_type": "notebook",
        "is_private": True,
        "enable_gpu": False,
        "enable_internet": True,
        "keywords": [],
        "dataset_sources": merge_dataset_ids(),
        "kernel_sources": [],
        "competition_sources": [],
        "model_sources": [],
    }


def write_payload(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    serialized = json.dumps(notebook, ensure_ascii=False)
    missing = [dataset_id for dataset_id in merge_dataset_ids() if dataset_id not in serialized]
    if missing:
        raise RuntimeError(f"Merge notebook is missing Dataset mappings: {missing}")
    if '"datasets", "download"' in serialized:
        raise RuntimeError("Merge notebook must consume attached inputs, not runtime downloads")
    code_path = destination / "typepro_merge_finalize.ipynb"
    metadata_path = destination / "kernel-metadata.json"
    shutil.copyfile(NOTEBOOK_PATH, code_path)
    metadata_path.write_text(
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
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = (result.stdout or "").strip()
    if result.returncode:
        raise RuntimeError(f"Cannot query merge kernel: {output}")
    return output


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--check-status", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "typepro_kernel_versions" / "merge_finalize",
    )
    args = parser.parse_args(argv)
    if args.push and args.check_status:
        parser.error("--push and --check-status are mutually exclusive")

    credential = load_credential(CREDENTIAL_PATH, OWNER)
    if args.check_status:
        with tempfile.TemporaryDirectory(prefix="typepro_merge_status_") as temp:
            status = kernel_status(credential, Path(temp))
        result = {"pushed": False, "status": status}
    elif args.push:
        with tempfile.TemporaryDirectory(prefix="typepro_merge_push_") as temp:
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
        "dataset_sources": merge_dataset_ids(),
        **result,
    }, indent=2))


if __name__ == "__main__":
    main()
