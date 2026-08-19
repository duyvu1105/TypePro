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
from generate_notebooks import validate_merge_datasets


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
OWNER = "duyvu1105"
KERNEL_SLUG = "merge-dataset"
NOTEBOOK_PATH = ROOT / "11_merge_finalize.ipynb"
MERGE_PLAN_PATH = ROOT / "shard_merge_plan.json"
CREDENTIAL_PATH = REPO_ROOT / "kaggle.json"


def merge_dataset_ids() -> list[str]:
    plan = json.loads(MERGE_PLAN_PATH.read_text(encoding="utf-8"))
    if plan.get("schema_version") != "typepro-shard-merge-plan-v3":
        raise RuntimeError("Unsupported ten-shard merge plan schema")
    if plan.get("final_dataset_owner") != OWNER:
        raise RuntimeError("Merge plan final owner does not match merge kernel owner")
    datasets = plan.get("datasets")
    if not isinstance(datasets, list) or len(datasets) != 10:
        raise RuntimeError("Merge plan must contain exactly 10 shard Datasets")
    validated = validate_merge_datasets(datasets, 10, OWNER)
    expected_coordinates = {(index, 10) for index in range(10)}
    actual_coordinates = {
        (item["shard_index"], item["shard_count"]) for item in validated
    }
    if actual_coordinates != expected_coordinates:
        raise RuntimeError(
            f"Merge plan partition coordinates differ: {actual_coordinates}"
        )
    result = [item["dataset_id"] for item in validated]
    if len(result) != len(set(result)):
        raise RuntimeError("Merge plan contains duplicate Dataset IDs")
    return result


def kernel_metadata(code_file: str) -> dict:
    return {
        "id": f"{OWNER}/{KERNEL_SLUG}",
        "title": "Merge Dataset",
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


def check_dataset_sources(
    credential: dict[str, str], config_dir: Path
) -> dict[str, str]:
    environment = os.environ.copy()
    environment["KAGGLE_CONFIG_DIR"] = str(config_dir)
    environment["KAGGLE_USERNAME"] = credential["username"]
    environment["KAGGLE_KEY"] = credential["key"]
    environment.pop("KAGGLE_API_TOKEN", None)
    statuses: dict[str, str] = {}
    for dataset_id in merge_dataset_ids():
        result = subprocess.run(
            ["kaggle", "datasets", "files", dataset_id, "--page-size", "10"],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        statuses[dataset_id] = "listable" if result.returncode == 0 else "unavailable"
    return statuses


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--check-status", action="store_true")
    parser.add_argument("--check-inputs", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "typepro_kernel_versions" / "merge_finalize",
    )
    args = parser.parse_args(argv)
    if sum((args.push, args.check_status, args.check_inputs)) > 1:
        parser.error("--push, --check-status and --check-inputs are mutually exclusive")

    credential = load_credential(CREDENTIAL_PATH, OWNER)
    if args.check_inputs:
        with tempfile.TemporaryDirectory(prefix="typepro_merge_inputs_") as temp:
            statuses = check_dataset_sources(credential, Path(temp))
        result = {"pushed": False, "input_statuses": statuses}
    elif args.check_status:
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
