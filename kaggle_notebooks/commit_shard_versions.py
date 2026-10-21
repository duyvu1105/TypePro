"""Validate, render, and optionally push ten standalone shard notebooks."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from generate_notebooks import SHARD_PART_COUNTS, physical_partitions


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
CONFIG_TAG = "typepro-shard-config"
OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,49}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,49}$")
SHARD_LINE_RE = re.compile(r"^SHARD_INDEX = \d+$", re.MULTILINE)
SHARD_COUNT_LINE_RE = re.compile(r"^SHARD_COUNT = \d+$", re.MULTILINE)
ASSIGNED_SHARDS_LINE_RE = re.compile(r"^ASSIGNED_SHARDS = \[\d+\]$", re.MULTILINE)
PUSH_ERROR_MARKERS = (
    "kernel push error:",
    "notebook not found",
    "not valid kernel sources",
    "not valid dataset sources",
)


@dataclass(frozen=True)
class AccountPlan:
    runner_account: str
    dataset_owner: str
    public_dataset: bool
    notebook_path: Path
    kernel_slug: str
    assigned_shards: tuple[int, ...]
    part_count: int = 1
    independent_parts: bool = False
    part_runner_accounts: tuple[str, ...] = ()
    final_dataset_owner: str = ""


def plan_for_part(plan: AccountPlan, part_index: int) -> AccountPlan:
    """Resolve the runner/publisher before rendering, authentication or scheduling."""
    if not 0 <= part_index < plan.part_count:
        raise ValueError(f"Invalid part index: {part_index}")
    if not plan.part_runner_accounts:
        return plan
    owner = plan.part_runner_accounts[part_index]
    return replace(plan, runner_account=owner, dataset_owner=owner,
                   public_dataset=owner.casefold() != plan.final_dataset_owner.casefold())


def load_plan(path: Path) -> tuple[str, int, list[AccountPlan]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "typepro-shard-account-plan-v3":
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
    for item in value.get("shards", []):
        account = item.get("runner_account")
        dataset_owner = item.get("dataset_owner")
        public_dataset = item.get("public_dataset")
        notebook_name = item.get("notebook")
        kernel_slug = item.get("kernel_slug")
        shard_index = item.get("shard_index")
        part_count = item.get("part_count", 1)
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
        if not isinstance(shard_index, int) or shard_index not in range(shard_count):
            raise RuntimeError(f"Invalid shard index: {shard_index!r}")
        expected_parts = len(physical_partitions(shard_index))
        if part_count != expected_parts:
            raise RuntimeError(
                f"Shard {shard_index:02d} must have {expected_parts} part(s), "
                f"found {part_count!r}"
            )
        part_runners = item.get('part_runner_accounts', [])
        if (not isinstance(part_runners, list)
                or (part_runners and (len(part_runners) != part_count
                    or not all(isinstance(runner, str) and OWNER_RE.fullmatch(runner) for runner in part_runners)
                    or not item.get('independent_parts')))):
            raise RuntimeError(f'Invalid part runner accounts for shard {shard_index}')
        plans.append(
            AccountPlan(
                runner_account=account,
                dataset_owner=dataset_owner,
                public_dataset=public_dataset,
                notebook_path=path.parent / notebook_name,
                kernel_slug=kernel_slug,
                assigned_shards=(shard_index,),
                part_count=part_count,
                independent_parts=bool(item.get('independent_parts', False)),
                part_runner_accounts=tuple(part_runners),
                final_dataset_owner=final_dataset_owner,
            )
        )
    if len(plans) != shard_count:
        raise RuntimeError(
            f"Expected exactly {shard_count} standalone shard notebooks, found {len(plans)}"
        )
    combined = [index for plan in plans for index in plan.assigned_shards]
    if sorted(combined) != list(range(shard_count)):
        raise RuntimeError(f"Account plan must cover shards 0..9 exactly once: {combined}")
    notebook_paths = [plan.notebook_path.resolve() for plan in plans]
    kernel_ids = [f"{plan.runner_account}/{plan.kernel_slug}".casefold() for plan in plans]
    if len(set(notebook_paths)) != shard_count or len(set(kernel_ids)) != shard_count:
        raise RuntimeError("Every shard must have a distinct notebook path and kernel ID")
    account_counts: dict[str, int] = {}
    for plan in plans:
        account_counts[plan.runner_account.casefold()] = (
            account_counts.get(plan.runner_account.casefold(), 0) + 1
        )
        should_be_public = (
            plan.dataset_owner.casefold() != final_dataset_owner.casefold()
        )
        if plan.public_dataset != should_be_public:
            raise RuntimeError(
                "The final owner's shards must be private and the other "
                f"account's shards must be public: {plan.runner_account!r}"
            )
    independent = all(plan.independent_parts for plan in plans)
    if independent:
        physical_counts = dict.fromkeys(account_counts, 0)
        for plan in plans:
            for part in range(plan.part_count):
                account = plan_for_part(plan, part).runner_account.casefold()
                if account not in physical_counts:
                    raise RuntimeError(f'Unknown partition runner: {account}')
                physical_counts[account] += 1
        shard_one = next(plan for plan in plans if plan.assigned_shards == (1,))
        if len(set(shard_one.part_runner_accounts)) != 3:
            raise RuntimeError('Shard 1 must assign one part to each account')
        if physical_counts != {'duyvu1105': 7, 'duymign': 7, 'vdduy1105': 7}:
            raise RuntimeError(f'Three-account partition counts must be 7/7/7: {physical_counts}')
    elif sorted(account_counts.values()) != [5, 5]:
        raise RuntimeError(
            f"Exactly two runner accounts must own five shards each: {account_counts}"
        )
    if not independent and any(
        plan.dataset_owner.casefold()
        != (final_dataset_owner if plan.assigned_shards[0] < 5 else plan.runner_account).casefold()
        for plan in plans
    ):
        raise RuntimeError("Shards 00-04 must belong to the final owner")
    return final_dataset_owner, shard_count, sorted(plans, key=lambda plan: plan.assigned_shards[0])


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
    *,
    physical_shard_index: int | None = None,
    physical_shard_count: int = 10,
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
    if not SHARD_COUNT_LINE_RE.search(source):
        raise RuntimeError("Standalone shard notebook must hard-code SHARD_COUNT")
    if f"ASSIGNED_SHARDS = [{shard_index}]" not in source:
        raise RuntimeError("Standalone shard notebook must assign exactly one shard")
    physical_shard_index = (
        shard_index if physical_shard_index is None else physical_shard_index
    )
    if (
        physical_shard_count <= 0
        or physical_shard_index not in range(physical_shard_count)
        or physical_shard_count % 10
        or physical_shard_index % 10 != shard_index
    ):
        raise ValueError(
            f"Invalid physical partition {physical_shard_index}/{physical_shard_count} "
            f"for logical shard {shard_index}"
        )
    replacements = []
    source, count = ASSIGNED_SHARDS_LINE_RE.subn(
        f"ASSIGNED_SHARDS = [{physical_shard_index}]", source
    )
    replacements.append(("ASSIGNED_SHARDS", count))
    source, count = SHARD_LINE_RE.subn(f"SHARD_INDEX = {physical_shard_index}", source)
    replacements.append(("SHARD_INDEX", count))
    source, count = SHARD_COUNT_LINE_RE.subn(f"SHARD_COUNT = {physical_shard_count}", source)
    replacements.append(("SHARD_COUNT", count))
    invalid = [name for name, count in replacements if count != 1]
    if invalid:
        raise RuntimeError(f"Expected one assignment for each of {invalid}")
    tagged[0]["source"] = source

    typepro = rendered.setdefault("metadata", {}).setdefault("typepro", {})
    if tuple(typepro.get("assigned_shards", [])) != expected_shards:
        raise RuntimeError("Notebook assigned_shards metadata does not match the account plan")
    if typepro.get("expected_dataset_owner") != dataset_owner:
        raise RuntimeError("Notebook Dataset owner does not match the account plan")
    if bool(typepro.get("public_dataset")) != public_dataset:
        raise RuntimeError("Notebook Dataset visibility does not match the account plan")
    typepro["rendered_shard_index"] = shard_index
    typepro["version_contract"] = "one-kaggle-notebook-builds-one-shard"
    return rendered


def render_part_version(template: dict[str, Any], plan: AccountPlan, part_index: int,
                        *, reuse_project_kb: bool | None = None) -> dict[str, Any]:
    """Apply an explicit part publisher while preserving template ownership checks."""
    effective = plan_for_part(plan, part_index)
    template = copy.deepcopy(template)
    metadata = template['metadata']['typepro']
    if (metadata.get('expected_dataset_owner') != plan.dataset_owner
            or bool(metadata.get('public_dataset')) != plan.public_dataset):
        raise RuntimeError('Template publisher does not match the logical shard plan')
    config = next(cell for cell in template['cells'] if CONFIG_TAG in cell.get('metadata', {}).get('tags', []))
    if reuse_project_kb is not None:
        config['source'], found = re.subn(r'^REUSE_PROJECT_KB = .+$',
            f'REUSE_PROJECT_KB = {reuse_project_kb!r}', config['source'], flags=re.MULTILINE)
        if found != 1:
            raise RuntimeError('Expected one REUSE_PROJECT_KB assignment; regenerate notebooks')
        metadata['reuse_project_kb'] = reuse_project_kb
    for name, value in (('EXPECTED_DATASET_OWNER', effective.dataset_owner),
                        ('PUBLISH_PUBLIC', effective.public_dataset)):
        config['source'], count = re.subn(r'^' + name + r' = .+$',
                                         f'{name} = {value!r}', config['source'], flags=re.MULTILINE)
        if count != 1:
            raise RuntimeError(f'Expected exactly one {name} assignment')
    metadata.update(expected_dataset_owner=effective.dataset_owner, public_dataset=effective.public_dataset)
    index, count = physical_partitions(plan.assigned_shards[0])[part_index]
    return render_shard_version(template, plan.assigned_shards[0], plan.assigned_shards,
                                effective.dataset_owner, effective.public_dataset,
                                physical_shard_index=index, physical_shard_count=count)


def kernel_metadata(
    plan: AccountPlan, code_file: str, *, part_index: int = 0, reuse_project_kb: bool = False
) -> dict[str, Any]:
    plan = plan_for_part(plan, part_index)
    shard_index = plan.assigned_shards[0]
    kernel_slug = partition_kernel_slug(plan, part_index)
    physical_index, physical_count = physical_partitions(shard_index)[part_index]
    kb_dataset = (f'{plan.dataset_owner}/typepro-build-shard-{physical_index:02d}'
                  + ('-of-40' if physical_count == 40 else ''))
    title = f"TypePro Python Shard {shard_index:02d}"
    if plan.independent_parts and shard_index == 2 and part_index > 0:
        title += f" Part 02 Subpart {part_index:02d}"
    elif plan.independent_parts and plan.part_count > 1:
        title += f" Part {part_index + 1:02d}"
    return {
        "id": f"{plan.runner_account}/{kernel_slug}",
        # Kaggle derives the effective slug from title even when `id` is set.
        "title": title,
        "code_file": code_file,
        "language": "python",
        "kernel_type": "notebook",
        "is_private": True,
        "enable_gpu": False,
        "enable_internet": True,
        "keywords": [],
        "dataset_sources": [kb_dataset] if reuse_project_kb else [],
        "kernel_sources": [],
        "competition_sources": [],
        "model_sources": [],
    }


def partition_kernel_slug(plan: AccountPlan, part_index: int) -> str:
    if part_index not in range(plan.part_count):
        raise ValueError(
            f"Part {part_index + 1} is outside shard {plan.assigned_shards[0]:02d} "
            f"with {plan.part_count} part(s)"
        )
    # Every part is a new version of the pre-existing logical-shard notebook.
    # Keep both the id and title stable so Kaggle cannot derive a new slug.
    if plan.independent_parts and plan.assigned_shards[0] == 2 and part_index > 0:
        return f'{plan.kernel_slug}-part-02-subpart-{part_index:02d}'
    if plan.independent_parts and plan.part_count > 1:
        return f'{plan.kernel_slug}-part-{part_index + 1:02d}'
    return plan.kernel_slug


def write_version(
    destination: Path,
    plan: AccountPlan,
    rendered: dict[str, Any],
    *,
    part_index: int = 0,
) -> tuple[Path, Path]:
    destination.mkdir(parents=True, exist_ok=True)
    code_path = destination / "typepro_shard.ipynb"
    metadata_path = destination / "kernel-metadata.json"
    code_path.write_text(
        json.dumps(rendered, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    metadata_path.write_text(
        json.dumps(kernel_metadata(plan, code_path.name, part_index=part_index,
            reuse_project_kb=bool(rendered.get('metadata', {}).get('typepro', {}).get('reuse_project_kb'))), indent=2),
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


def kernel_status(
    kernel: str, credential: dict[str, str], config_dir: Path
) -> str:
    environment = os.environ.copy()
    environment["KAGGLE_CONFIG_DIR"] = str(config_dir)
    environment["KAGGLE_USERNAME"] = credential["username"]
    environment["KAGGLE_KEY"] = credential["key"]
    environment.pop("KAGGLE_API_TOKEN", None)
    result = subprocess.run(
        ["kaggle", "kernels", "status", kernel],
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = (result.stdout or "").strip()
    if result.returncode:
        raise RuntimeError(f"Cannot query {kernel}: {output}")
    return output


def parse_credentials(values: list[str], plans: list[AccountPlan]) -> dict[str, Path]:
    if not values:
        defaults = [REPO_ROOT / "kaggle.json", REPO_ROOT / "kaggle2.json", REPO_ROOT / "kaggle3.json"]
        accounts = list(dict.fromkeys(
            plan.runner_account.casefold() for plan in plans
        ))
        if len(accounts) not in (2, 3):
            raise ValueError(f"Expected two or three runner accounts, found {accounts}")
        return {
            account: path
            for account, path in zip(accounts, defaults[:len(accounts)], strict=True)
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
    parser.add_argument(
        "--part",
        type=int,
        help="Push/render only this 1-based part; requires exactly one --shard",
    )
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--reuse-project-kb", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--check-status", action="store_true")
    args = parser.parse_args(argv)
    if args.push and args.check_status:
        parser.error("--push and --check-status are mutually exclusive")

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
    if args.part is not None and len(requested_shards) != 1:
        raise ValueError("--part requires exactly one --shard")
    if args.part is not None:
        selected_plan = next(
            plan for plan in plans
            if plan.assigned_shards[0] in requested_shards
        )
        partition_kernel_slug(selected_plan, args.part - 1)
    summaries = []
    for plan in plans:
        template = json.loads(plan.notebook_path.read_text(encoding="utf-8"))
        shard_index = plan.assigned_shards[0]
        if shard_index not in requested_shards:
            continue
        partitions = physical_partitions(shard_index)
        for part_index, (physical_shard_index, physical_shard_count) in enumerate(partitions):
            if args.part is not None and part_index != args.part - 1:
                continue
            part_plan = plan_for_part(plan, part_index)
            credential = load_credential(credential_paths[part_plan.runner_account.casefold()], part_plan.runner_account)
            rendered = render_part_version(template, plan, part_index, reuse_project_kb=args.reuse_project_kb)
            kernel_slug = partition_kernel_slug(plan, part_index)
            summary = {
                "runner_account": part_plan.runner_account,
                "kernel": f"{part_plan.runner_account}/{kernel_slug}",
                "notebook": part_plan.notebook_path.name,
                "logical_shard_index": shard_index,
                "part_index": part_index,
                "part_count": part_plan.part_count,
                "shard_index": physical_shard_index,
                "shard_count": physical_shard_count,
                "dataset_id": (
                    f"{part_plan.dataset_owner}/"
                    f"typepro-build-shard-{physical_shard_index:02d}"
                    + ("-of-40" if physical_shard_count == 40 else "")
                ),
            }
            if args.check_status:
                with tempfile.TemporaryDirectory(prefix="typepro_kernel_status_") as temp:
                    auth_dir = Path(temp) / "auth"
                    auth_dir.mkdir(parents=True)
                    status = kernel_status(summary["kernel"], credential, auth_dir)
                summaries.append({**summary, "status": status})
            elif args.push:
                with tempfile.TemporaryDirectory(prefix="typepro_kernel_push_") as temp:
                    push_dir = Path(temp) / "payload"
                    auth_dir = Path(temp) / "auth"
                    auth_dir.mkdir(parents=True)
                    write_version(
                        push_dir, part_plan, rendered, part_index=part_index
                    )
                    output = run_push(push_dir, credential, auth_dir)
                summaries.append({**summary, "pushed": True, "cli_output": output})
            else:
                destination = (
                    args.output_dir.resolve()
                    / part_plan.runner_account
                    / f"shard_{shard_index:02d}_part_{part_index + 1:02d}"
                )
                write_version(
                    destination, part_plan, rendered, part_index=part_index
                )
                summaries.append({
                    **summary, "pushed": False, "rendered_to": str(destination),
                })
    print(json.dumps({
        "final_dataset_owner": final_dataset_owner,
        "shard_dataset_owners": {
            plan.runner_account: plan.dataset_owner for plan in plans
        },
        "notebooks": summaries,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
