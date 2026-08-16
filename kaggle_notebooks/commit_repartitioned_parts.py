"""Render or push the six replacements for two cancelled half-shard jobs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from commit_shard_versions import load_credential, run_push
from generate_notebooks import repartitioned_shard_notebook


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
REPOSITORY = "https://github.com/duyvu1105/TypePro.git"
BRANCH = "main"


@dataclass(frozen=True)
class ReplacementJob:
    runner_account: str
    credential_path: Path
    logical_shard_index: int
    parent_part_index: int
    subpart_index: int
    public_dataset: bool

    @property
    def parent_residue(self) -> int:
        return self.logical_shard_index + 10 * self.parent_part_index

    @property
    def shard_index(self) -> int:
        return self.parent_residue + 20 * self.subpart_index

    @property
    def shard_count(self) -> int:
        return 60

    @property
    def part_letter(self) -> str:
        return chr(ord("A") + self.parent_part_index)

    @property
    def kernel_slug(self) -> str:
        return (
            f"typepro-shard-{self.logical_shard_index:02d}-10-part-"
            f"{self.part_letter.lower()}{self.subpart_index + 1}-3"
        )

    @property
    def dataset_id(self) -> str:
        return f"{self.runner_account}/typepro-build-shard-{self.shard_index:02d}"


def replacement_jobs() -> list[ReplacementJob]:
    return [
        *(
            ReplacementJob(
                "duyvu1105", REPO_ROOT / "kaggle.json", 1, 0, subpart, False
            )
            for subpart in range(3)
        ),
        *(
            ReplacementJob(
                "duymign", REPO_ROOT / "kaggle2.json", 4, 1, subpart, True
            )
            for subpart in range(3)
        ),
    ]


def select_jobs(jobs: list[ReplacementJob], requested: list[str]) -> list[ReplacementJob]:
    if not requested:
        return jobs
    requested_slugs = set(requested)
    selected = [job for job in jobs if job.kernel_slug in requested_slugs]
    missing = requested_slugs - {job.kernel_slug for job in selected}
    if missing:
        raise ValueError(f"Unknown replacement kernel slug(s): {sorted(missing)}")
    return selected


def kernel_metadata(job: ReplacementJob, code_file: str) -> dict[str, Any]:
    return {
        "id": f"{job.runner_account}/{job.kernel_slug}",
        "title": (
            f"TypePro shard {job.logical_shard_index:02d}/10 part "
            f"{job.part_letter}{job.subpart_index + 1}/3"
        ),
        "code_file": code_file,
        "language": "python",
        "kernel_type": "notebook",
        "is_private": True,
        "enable_gpu": False,
        "enable_internet": True,
        "keywords": [],
        "dataset_sources": [],
        "kernel_sources": [],
        "competition_sources": [],
        "model_sources": [],
    }


def write_job(destination: Path, job: ReplacementJob) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    code_path = destination / "typepro_repartitioned_shard.ipynb"
    metadata_path = destination / "kernel-metadata.json"
    rendered = repartitioned_shard_notebook(
        job.logical_shard_index,
        job.parent_part_index,
        job.subpart_index,
        REPOSITORY,
        BRANCH,
        expected_dataset_owner=job.runner_account,
        public_dataset=job.public_dataset,
    )
    code_path.write_text(
        json.dumps(rendered, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    metadata_path.write_text(
        json.dumps(kernel_metadata(job, code_path.name), indent=2), encoding="utf-8"
    )
    json.loads(code_path.read_text(encoding="utf-8"))
    json.loads(metadata_path.read_text(encoding="utf-8"))


def kernel_status(
    job: ReplacementJob,
    credential: dict[str, str],
    config_dir: Path,
) -> str:
    environment = os.environ.copy()
    environment["KAGGLE_CONFIG_DIR"] = str(config_dir)
    environment["KAGGLE_USERNAME"] = credential["username"]
    environment["KAGGLE_KEY"] = credential["key"]
    environment.pop("KAGGLE_API_TOKEN", None)
    result = subprocess.run(
        ["kaggle", "kernels", "status", f"{job.runner_account}/{job.kernel_slug}"],
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = (result.stdout or "").strip()
    if result.returncode:
        raise RuntimeError(
            f"Cannot query {job.runner_account}/{job.kernel_slug}: {output}"
        )
    return output


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "typepro_kernel_versions" / "repartitioned_parts",
    )
    parser.add_argument("--push", action="store_true")
    parser.add_argument(
        "--job",
        action="append",
        default=[],
        help="Render/push/check only this kernel slug; repeat for multiple jobs",
    )
    parser.add_argument(
        "--check-status",
        action="store_true",
        help="Query the six remote kernels without rendering or pushing",
    )
    args = parser.parse_args(argv)
    if args.push and args.check_status:
        parser.error("--push and --check-status are mutually exclusive")

    summaries = []
    jobs = select_jobs(replacement_jobs(), args.job)
    for job in jobs:
        credential = load_credential(job.credential_path, job.runner_account)
        status = None
        if args.check_status:
            with tempfile.TemporaryDirectory(prefix="typepro_repartition_status_") as temp:
                status = kernel_status(job, credential, Path(temp))
            output = None
            rendered_to = None
        elif args.push:
            with tempfile.TemporaryDirectory(prefix="typepro_repartition_push_") as temp:
                push_dir = Path(temp) / "payload"
                auth_dir = Path(temp) / "auth"
                auth_dir.mkdir(parents=True)
                write_job(push_dir, job)
                output = run_push(push_dir, credential, auth_dir)
            rendered_to = None
        else:
            destination = args.output_dir.resolve() / job.runner_account / job.kernel_slug
            write_job(destination, job)
            output = None
            rendered_to = str(destination)
        summaries.append({
            "runner_account": job.runner_account,
            "kernel": f"{job.runner_account}/{job.kernel_slug}",
            "dataset_id": job.dataset_id,
            "logical_shard_index": job.logical_shard_index,
            "parent_part": f"{job.part_letter}/2",
            "subpart": f"{job.subpart_index + 1}/3",
            "physical_shard": f"{job.shard_index}/{job.shard_count}",
            "public_dataset": job.public_dataset,
            "pushed": args.push,
            "status": status,
            "rendered_to": rendered_to,
            "cli_output": output,
        })
    print(json.dumps({
        "coverage_proof": {
            "shard_01_parent_1_over_20": ["1/60", "21/60", "41/60"],
            "shard_04_parent_14_over_20": ["14/60", "34/60", "54/60"],
        },
        "jobs_per_account": {
            account: sum(job.runner_account == account for job in jobs)
            for account in ("duyvu1105", "duymign")
        },
        "jobs": summaries,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
