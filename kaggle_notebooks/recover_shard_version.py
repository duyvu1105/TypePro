"""Push a publish-only Kaggle notebook for one completed shard version."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import commit_shard_versions
import generate_notebooks


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent


def parse_source(value: str) -> tuple[int, int]:
    try:
        shard_text, version_text = value.split("=", 1)
        shard = int(shard_text)
        version = int(version_text)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError(
            "--source-version must use SHARD=VERSION, for example 8=9"
        ) from exc
    if not 0 <= shard < 10 or version <= 0:
        raise argparse.ArgumentTypeError(f"Invalid shard/version mapping: {value!r}")
    return shard, version


def recovery_metadata(
    account: commit_shard_versions.AccountPlan,
    shard: int,
    version: int,
    code_file: str,
) -> dict:
    return {
        "id": (
            f"{account.runner_account}/typepro-recover-shard-"
            f"{shard:02d}-from-v{version}"
        ),
        "title": f"TypePro Recover Shard {shard:02d} From V{version}",
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


def write_payload(
    destination: Path,
    notebook: dict,
    metadata: dict,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    code_path = destination / "recover_shard.ipynb"
    metadata_path = destination / "kernel-metadata.json"
    code_path.write_text(
        json.dumps(notebook, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    json.loads(code_path.read_text(encoding="utf-8"))
    json.loads(metadata_path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--plan", type=Path, default=ROOT / "shard_account_plan.json"
    )
    parser.add_argument(
        "--source-version",
        required=True,
        type=parse_source,
        metavar="SHARD=VERSION",
    )
    parser.add_argument(
        "--credential",
        action="append",
        default=[],
        help="Runner credential mapping USERNAME=PATH; repeat once per account",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "typepro_kernel_versions" / "recovery",
    )
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args(argv)

    final_owner, shard_count, plans = commit_shard_versions.load_plan(
        args.plan.resolve()
    )
    shard, source_version = args.source_version
    account = next(
        (plan for plan in plans if shard in plan.assigned_shards), None
    )
    if account is None:
        raise RuntimeError(f"Shard {shard} is not assigned by the account plan")
    source_kernel = (
        f"{account.runner_account}/{account.kernel_slug}/{source_version}"
    )
    notebook = generate_notebooks.recovery_notebook(
        shard,
        shard_count,
        "https://github.com/duyvu1105/TypePro.git",
        "main",
        expected_dataset_owner=account.dataset_owner,
        public_dataset=account.public_dataset,
        source_kernel=source_kernel,
    )
    metadata = recovery_metadata(
        account, shard, source_version, "recover_shard.ipynb"
    )
    credential_paths = commit_shard_versions.parse_credentials(
        args.credential, plans
    )
    credential = commit_shard_versions.load_credential(
        credential_paths[account.runner_account.casefold()],
        account.runner_account,
    )

    if args.push:
        with tempfile.TemporaryDirectory(prefix="typepro_recovery_push_") as temp:
            push_dir = Path(temp) / "payload"
            auth_dir = Path(temp) / "auth"
            auth_dir.mkdir(parents=True)
            write_payload(push_dir, notebook, metadata)
            output = commit_shard_versions.run_push(
                push_dir, credential, auth_dir
            )
        result = {"pushed": True, "cli_output": output}
    else:
        destination = (
            args.output_dir.resolve()
            / account.runner_account
            / f"shard_{shard:02d}_from_v{source_version}"
        )
        write_payload(destination, notebook, metadata)
        result = {"pushed": False, "rendered_to": str(destination)}

    print(json.dumps({
        "final_dataset_owner": final_owner,
        "runner_account": account.runner_account,
        "dataset_owner": account.dataset_owner,
        "public_dataset": account.public_dataset,
        "shard": shard,
        "source_kernel": source_kernel,
        "recovery_kernel": metadata["id"],
        **result,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
