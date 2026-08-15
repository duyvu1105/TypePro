"""Render and optionally push five shard versions to each Kaggle account.

Two remote notebook slugs are used, one per runner account.  Each push embeds a
single immutable ``SHARD_INDEX`` so every Kaggle version builds exactly one
shard. Host-account credentials are used only for ``kernels push``; each
generated notebook validates and uses its same-account Kaggle host identity.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
CONFIG_TAG = "typepro-shard-config"
OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,49}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,49}$")
SHARD_LINE_RE = re.compile(r"^SHARD_INDEX = \d+$", re.MULTILINE)
PUSH_ERROR_MARKERS = ("kernel push error:", "notebook not found")


@dataclass(frozen=True)
class AccountPlan:
    runner_account: str
    dataset_owner: str
    public_dataset: bool
    notebook_path: Path
    kernel_slug: str
    assigned_shards: tuple[int, ...]


def load_plan(path: Path) -> tuple[str, int, list[AccountPlan]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "typepro-shard-account-plan-v2":
        raise RuntimeError(f"Unsupported account plan: {path}")
    final_dataset_owner = value.get("final_dataset_owner")
    shard_count = value.get("shard_count")
    if (
        not isinstance(final_dataset_owner, str)
        or not OWNER_RE.fullmatch(final_dataset_owner)
    ):
        raise RuntimeError(
            f"Invalid final Dataset owner in {path}: {final_dataset_owner!r}"
        )
    if shard_count != 10:
        raise RuntimeError(f"Expected exactly 10 shards, found {shard_count!r}")

    plans: list[AccountPlan] = []
    for item in value.get("accounts", []):
        account = item.get("runner_account")
        dataset_owner = item.get("dataset_owner")
        public_dataset = item.get("public_dataset")
        notebook_name = item.get("notebook")
        kernel_slug = item.get("kernel_slug")
        shards = item.get("assigned_shards")
        if not isinstance(account, str) or not OWNER_RE.fullmatch(account):
            raise RuntimeError(f"Invalid runner account: {account!r}")
        if not isinstance(dataset_owner, str) or not OWNER_RE.fullmatch(dataset_owner):
            raise RuntimeError(f"Invalid shard Dataset owner: {dataset_owner!r}")
        if dataset_owner.casefold() != account.casefold():
            raise RuntimeError(
                f"Runner {account!r} must publish its own shard Datasets, not "
                f"{dataset_owner!r}"
            )
        if not isinstance(public_dataset, bool):
            raise RuntimeError(f"public_dataset must be boolean for {account!r}")
        if not isinstance(notebook_name, str) or Path(notebook_name).name != notebook_name:
            raise RuntimeError(f"Invalid notebook filename: {notebook_name!r}")
        if not isinstance(kernel_slug, str) or not SLUG_RE.fullmatch(kernel_slug):
            raise RuntimeError(f"Invalid kernel slug: {kernel_slug!r}")
        if (
            not isinstance(shards, list)
            or len(shards) != 5
            or any(not isinstance(index, int) for index in shards)
            or len(set(shards)) != 5
        ):
            raise RuntimeError(f"Each account must own exactly five unique shards: {shards!r}")
        plans.append(
            AccountPlan(
                runner_account=account,
                dataset_owner=dataset_owner,
                public_dataset=public_dataset,
                notebook_path=path.parent / notebook_name,
                kernel_slug=kernel_slug,
                assigned_shards=tuple(shards),
            )
        )
    if len(plans) != 2:
        raise RuntimeError(f"Expected exactly two runner accounts, found {len(plans)}")
    combined = [index for plan in plans for index in plan.assigned_shards]
    if sorted(combined) != list(range(shard_count)):
        raise RuntimeError(f"Account plan must cover shards 0..9 exactly once: {combined}")
    for plan in plans:
        should_be_public = (
            plan.dataset_owner.casefold() != final_dataset_owner.casefold()
        )
        if plan.public_dataset != should_be_public:
            raise RuntimeError(
                "The final owner's shards must be private and the other "
                f"account's shards must be public: {plan.runner_account!r}"
            )
    return final_dataset_owner, shard_count, plans


def load_credential(path: Path, expected_username: str) -> dict[str, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read Kaggle credential {path}: {exc}") from exc
    username = value.get("username")
    key = value.get("key")
    if not isinstance(username, str) or not username.strip():
        raise RuntimeError(f"Credential username is missing in {path}")
    if not isinstance(key, str) or not key.strip():
        raise RuntimeError(f"Credential key is missing in {path}")
    if username.strip().casefold() != expected_username.casefold():
        raise RuntimeError(
            f"Credential {path} belongs to {username!r}, expected {expected_username!r}"
        )
    return {"username": username.strip(), "key": key.strip()}


def render_shard_version(
    template: dict[str, Any],
    shard_index: int,
    expected_shards: tuple[int, ...],
    dataset_owner: str,
    public_dataset: bool,
) -> dict[str, Any]:
    if shard_index not in expected_shards:
        raise ValueError(f"Shard {shard_index} is not assigned to {expected_shards}")
    rendered = copy.deepcopy(template)
    tagged = [
        cell
        for cell in rendered.get("cells", [])
        if CONFIG_TAG in cell.get("metadata", {}).get("tags", [])
    ]
    if len(tagged) != 1:
        raise RuntimeError(f"Expected one {CONFIG_TAG!r} cell, found {len(tagged)}")
    source = tagged[0].get("source")
    if not isinstance(source, str):
        raise RuntimeError("Tagged shard config cell must contain string source")
    source, replacements = SHARD_LINE_RE.subn(f"SHARD_INDEX = {shard_index}", source)
    if replacements != 1:
        raise RuntimeError(f"Expected one SHARD_INDEX assignment, replaced {replacements}")
    tagged[0]["source"] = source

    typepro = rendered.setdefault("metadata", {}).setdefault("typepro", {})
    if tuple(typepro.get("assigned_shards", [])) != expected_shards:
        raise RuntimeError("Notebook assigned_shards metadata does not match the account plan")
    if typepro.get("expected_dataset_owner") != dataset_owner:
        raise RuntimeError("Notebook Dataset owner does not match the account plan")
    if bool(typepro.get("public_dataset")) != public_dataset:
        raise RuntimeError("Notebook Dataset visibility does not match the account plan")
    typepro["rendered_shard_index"] = shard_index
    typepro["version_contract"] = "one-kaggle-version-builds-one-shard"
    return rendered


def kernel_metadata(plan: AccountPlan, code_file: str) -> dict[str, Any]:
    return {
        "id": f"{plan.runner_account}/{plan.kernel_slug}",
        "title": (
            f"TypePro shards {plan.assigned_shards[0]:02d}-"
            f"{plan.assigned_shards[-1]:02d}"
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


def write_version(
    destination: Path,
    plan: AccountPlan,
    rendered: dict[str, Any],
) -> tuple[Path, Path]:
    destination.mkdir(parents=True, exist_ok=True)
    code_path = destination / "typepro_shard.ipynb"
    metadata_path = destination / "kernel-metadata.json"
    code_path.write_text(
        json.dumps(rendered, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    metadata_path.write_text(
        json.dumps(kernel_metadata(plan, code_path.name), indent=2),
        encoding="utf-8",
    )
    # Read both files back so a partial write can never be pushed.
    json.loads(code_path.read_text(encoding="utf-8"))
    json.loads(metadata_path.read_text(encoding="utf-8"))
    return code_path, metadata_path


def run_push(directory: Path, credential: dict[str, str], config_dir: Path) -> str:
    environment = os.environ.copy()
    environment["KAGGLE_CONFIG_DIR"] = str(config_dir)
    environment["KAGGLE_USERNAME"] = credential["username"]
    environment["KAGGLE_KEY"] = credential["key"]
    environment.pop("KAGGLE_API_TOKEN", None)
    result = subprocess.run(
        ["kaggle", "kernels", "push", "-p", str(directory)],
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = (result.stdout or "").strip()
    lowered = output.casefold()
    if result.returncode or any(marker in lowered for marker in PUSH_ERROR_MARKERS):
        raise RuntimeError(
            f"Kaggle kernel push failed (exit {result.returncode}): {output}"
        )
    return output


def parse_credentials(values: list[str], plans: list[AccountPlan]) -> dict[str, Path]:
    if not values:
        defaults = [REPO_ROOT / "kaggle.json", REPO_ROOT / "kaggle2.json"]
        return {
            plan.runner_account.casefold(): path
            for plan, path in zip(plans, defaults, strict=True)
        }
    parsed: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--credential must use USERNAME=PATH")
        username, raw_path = value.split("=", 1)
        parsed[username.strip().casefold()] = Path(raw_path).expanduser().resolve()
    expected = {plan.runner_account.casefold() for plan in plans}
    if set(parsed) != expected:
        raise ValueError(f"Credential users must be exactly {sorted(expected)}")
    return parsed


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--plan",
        type=Path,
        default=ROOT / "shard_account_plan.json",
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
        default=REPO_ROOT / "typepro_kernel_versions",
        help="Dry-run output; ignored when --push is used",
    )
    parser.add_argument(
        "--shard",
        type=int,
        action="append",
        default=[],
        help="Render/push only this shard; repeat for multiple shards",
    )
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args(argv)

    plan_path = args.plan.resolve()
    final_dataset_owner, _, plans = load_plan(plan_path)
    credential_paths = parse_credentials(args.credential, plans)
    planned_shards = {
        index for plan in plans for index in plan.assigned_shards
    }
    requested_shards = set(args.shard) if args.shard else planned_shards
    invalid_shards = requested_shards - planned_shards
    if invalid_shards:
        raise ValueError(f"Requested shards are outside the plan: {sorted(invalid_shards)}")
    summaries = []
    for plan in plans:
        template = json.loads(plan.notebook_path.read_text(encoding="utf-8"))
        credential_path = credential_paths[plan.runner_account.casefold()]
        credential = load_credential(credential_path, plan.runner_account)
        for version_number, shard_index in enumerate(plan.assigned_shards, start=1):
            if shard_index not in requested_shards:
                continue
            rendered = render_shard_version(
                template,
                shard_index,
                plan.assigned_shards,
                plan.dataset_owner,
                plan.public_dataset,
            )
            if args.push:
                with tempfile.TemporaryDirectory(prefix="typepro_kernel_push_") as temp:
                    push_dir = Path(temp) / "payload"
                    auth_dir = Path(temp) / "auth"
                    auth_dir.mkdir(parents=True)
                    write_version(push_dir, plan, rendered)
                    output = run_push(push_dir, credential, auth_dir)
                summaries.append({
                    "runner_account": plan.runner_account,
                    "kernel": f"{plan.runner_account}/{plan.kernel_slug}",
                    "version_in_batch": version_number,
                    "shard_index": shard_index,
                    "pushed": True,
                    "cli_output": output,
                })
            else:
                destination = (
                    args.output_dir.resolve()
                    / plan.runner_account
                    / f"version_{version_number:02d}_shard_{shard_index:02d}"
                )
                write_version(destination, plan, rendered)
                summaries.append({
                    "runner_account": plan.runner_account,
                    "kernel": f"{plan.runner_account}/{plan.kernel_slug}",
                    "version_in_batch": version_number,
                    "shard_index": shard_index,
                    "pushed": False,
                    "rendered_to": str(destination),
                })
    print(json.dumps({
        "final_dataset_owner": final_dataset_owner,
        "shard_dataset_owners": {
            plan.runner_account: plan.dataset_owner for plan in plans
        },
        "versions": summaries,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
