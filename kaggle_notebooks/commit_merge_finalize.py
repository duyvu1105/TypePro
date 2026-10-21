"""Render, push, or inspect the final merge notebook under its Dataset owner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from commit_shard_versions import load_credential, run_push
from generate_notebooks import physical_partitions, validate_merge_datasets, republish_final_notebook, pinned_checkout_source


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
    expected_dataset_count = sum(len(physical_partitions(index)) for index in range(10))
    if not isinstance(datasets, list) or len(datasets) != expected_dataset_count:
        raise RuntimeError(
            f"Merge plan must contain exactly {expected_dataset_count} physical "
            "shard Datasets"
        )
    validated = validate_merge_datasets(datasets, 10, OWNER)
    expected_coordinates = {
        coordinate
        for index in range(10)
        for coordinate in physical_partitions(index)
    }
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


def write_payload(destination: Path, *, republish: bool = False,
                  revision: str | None = None, source_bundle: bytes | None = None) -> None:
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
    if republish:
        notebook = republish_final_notebook(notebook)
    if source_bundle is not None and revision is None:
        raise ValueError('Source bundle requires a pinned revision')
    if revision is not None:
        if not re.fullmatch(r'[0-9a-f]{40}', revision):
            raise ValueError('Revision must be a full Git commit SHA')
        cells = [c for c in notebook['cells'] if '"git", "clone"' in ''.join(c.get('source', []))]
        if len(cells) != 1:
            raise ValueError('Expected exactly one repository checkout cell')
        source = ''.join(cells[0]['source'])
        marker = '\nPIPELINE_DIR = '
        if marker not in source:
            raise ValueError('Expected pipeline setup after clone')
        cells[0]['source'] = source.replace(marker, pinned_checkout_source(revision, source_bundle) + marker, 1)
        notebook.setdefault('metadata', {}).setdefault('typepro', {}).update(
            source_revision=revision,
            source_bundle_sha256=hashlib.sha256(source_bundle).hexdigest() if source_bundle is not None else None)
    if republish or revision is not None:
        code_path.write_text(json.dumps(notebook, indent=1), encoding='utf-8')
    else:
        shutil.copyfile(NOTEBOOK_PATH, code_path)
    metadata = kernel_metadata(code_path.name)
    if republish:
        metadata.update(
            id=f"{OWNER}/republish-final-from-merge",
            title="Republish Final From Completed Merge",
            dataset_sources=[],
            kernel_sources=[f"{OWNER}/{KERNEL_SLUG}"],
        )
    metadata_path.write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )


def kernel_status(credential: dict[str, str], config_dir: Path, kernel_slug: str = KERNEL_SLUG) -> str:
    environment = os.environ.copy()
    environment["KAGGLE_CONFIG_DIR"] = str(config_dir)
    environment["KAGGLE_USERNAME"] = credential["username"]
    environment["KAGGLE_KEY"] = credential["key"]
    environment.pop("KAGGLE_API_TOKEN", None)
    result = subprocess.run(
        ["kaggle", "kernels", "status", f"{OWNER}/{kernel_slug}"],
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
    parser.add_argument("--republish-from-merge-output", action="store_true")
    parser.add_argument("--check-status", action="store_true")
    parser.add_argument("--check-inputs", action="store_true")
    parser.add_argument('--revision', help='Pin checkout to a full main commit SHA')
    parser.add_argument('--source-bundle', type=Path, help='Embed the pinned commit when it is not on GitHub yet')
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "typepro_kernel_versions" / "merge_finalize",
    )
    args = parser.parse_args(argv)
    if args.source_bundle and not args.revision:
        parser.error('--source-bundle requires --revision')
    bundle = args.source_bundle.read_bytes() if args.source_bundle else None
    if args.revision:
        if not re.fullmatch(r'[0-9a-f]{40}', args.revision):
            parser.error('--revision must be a full Git commit SHA')
        subprocess.run(['git', 'merge-base', '--is-ancestor', args.revision, 'main'], cwd=REPO_ROOT, check=True)
    if args.source_bundle:
        heads = subprocess.check_output(['git', 'bundle', 'list-heads', str(args.source_bundle.resolve())], cwd=REPO_ROOT, text=True)
        if not any(line.split()[0] == args.revision for line in heads.splitlines()):
            parser.error('Source bundle does not advertise the requested revision')
        subprocess.run(['git', 'bundle', 'verify', str(args.source_bundle.resolve())], cwd=REPO_ROOT, check=True, capture_output=True)
    if sum((args.push, args.check_status, args.check_inputs)) > 1:
        parser.error("--push, --check-status and --check-inputs are mutually exclusive")

    credential = load_credential(CREDENTIAL_PATH, OWNER)
    if args.check_inputs:
        with tempfile.TemporaryDirectory(prefix="typepro_merge_inputs_") as temp:
            statuses = check_dataset_sources(credential, Path(temp))
        result = {"pushed": False, "input_statuses": statuses}
    elif args.check_status:
        with tempfile.TemporaryDirectory(prefix="typepro_merge_status_") as temp:
            status = kernel_status(credential, Path(temp), "republish-final-from-merge" if args.republish_from_merge_output else KERNEL_SLUG)
        result = {"pushed": False, "status": status}
    elif args.push:
        with tempfile.TemporaryDirectory(prefix="typepro_merge_push_") as temp:
            payload = Path(temp) / "payload"
            auth = Path(temp) / "auth"
            auth.mkdir()
            write_payload(payload, republish=args.republish_from_merge_output,
                          revision=args.revision, source_bundle=bundle)
            output = run_push(payload, credential, auth)
        result = {"pushed": True, "cli_output": output}
    else:
        destination = args.output_dir.resolve()
        write_payload(destination, republish=args.republish_from_merge_output,
                      revision=args.revision, source_bundle=bundle)
        result = {"pushed": False, "rendered_to": str(destination)}

    print(json.dumps({
        "kernel": f"{OWNER}/republish-final-from-merge" if args.republish_from_merge_output else f"{OWNER}/{KERNEL_SLUG}",
        "dataset_sources": [] if args.republish_from_merge_output else merge_dataset_ids(),
        "kernel_sources": [f"{OWNER}/{KERNEL_SLUG}"] if args.republish_from_merge_output else [],
        **result,
    }, indent=2))


if __name__ == "__main__":
    main()
