"""One-time, resumable TypePro dataset builder for Kaggle.

The builder currently targets the Python experiment because the public TypeGen
release provides the Python annotation schema consumed by TypePro. It clones
one repository at a time, exports slices, and removes the checkout by default
to stay within Kaggle's working-disk limit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import stat
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from data_utils import is_builtin_annotation, iter_records, json_preview, print_jsonl_samples
from tqdm.auto import tqdm


TYPEGEN_URL = "https://github.com/JohnnyPeng18/TypeGen/releases/download/data/data.zip"
TYPEGEN_SHA256 = "3e58c9df31f7c845c5a9c97596587acbd70e67c824de27ab9e3a8b15b0c385ae"
TYPEGEN_FILES = (
    "data/trainset.json",
    "data/testset.json",
    "data/testset_randomsampled.json",
)
PROJECT_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SCHEMA_VERSION = "typepro-codet5p-parameter-third-party-v2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and cache TypePro contrastive data")
    parser.add_argument("--stage", choices=("all", "metadata", "slice", "finalize"), default="all")
    parser.add_argument("--typepro-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--work-dir", default="/kaggle/working/typepro_build")
    parser.add_argument("--output-dir", default="/kaggle/working/typepro_contrastive_dataset")
    parser.add_argument("--archive", help="Use an existing TypeGen data.zip instead of downloading")
    parser.add_argument("--split-profile", choices=("paper_project", "typegen_release"), default="paper_project")
    parser.add_argument("--validation-project-ratio", type=float, default=0.10)
    parser.add_argument("--test-projects", type=int, default=100)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--max-projects", type=int, default=0, help="Smoke test only; 0 processes all")
    parser.add_argument("--repos-root", help="Optional existing repos root containing owner/repository")
    parser.add_argument("--third-party-kb", help="Optional TypePro third-party JSON knowledge-base directory")
    parser.add_argument(
        "--build-import-kb", action=argparse.BooleanOptionalAction, default=True,
        help="Build third-party class JSON from packages imported by each cloned project",
    )
    parser.add_argument(
        "--download-missing-imports", action=argparse.BooleanOptionalAction, default=True,
        help="Download a wheel without dependencies when an imported package is not installed",
    )
    parser.add_argument("--kb-max-files-per-package", type=int, default=3000)
    parser.add_argument("--keep-repos", action="store_true")
    parser.add_argument("--force-metadata", action="store_true")
    parser.add_argument("--force-projects", action="store_true")
    parser.add_argument(
        "--skip-project",
        action="append",
        default=[],
        help=(
            "Skip owner/repository values containing this case-insensitive pattern; "
            "repeatable"
        ),
    )
    parser.add_argument(
        "--retrieval-schema-version",
        default="typepro-legacy-retrieval",
        help="Invalidates restored raw slices when recommendation logic changes",
    )
    parser.add_argument("--max-negatives", type=int, default=7)
    parser.add_argument("--missing-positive", choices=("drop", "append"), default="drop")
    parser.add_argument("--skip-sha256", action="store_true")
    parser.add_argument("--allow-partial", action="store_true", help="Allow finalization with missing/failed repositories")
    parser.add_argument("--strict-projects", action="store_true", help="Fail finalization if any repository could not be processed")
    parser.add_argument("--preview-samples", type=int, default=2, help="Samples printed per split/stage; 0 disables")
    parser.add_argument("--preview-max-chars", type=int, default=1600, help="Maximum characters per sample; 0 prints all")
    parser.add_argument("--log-every", type=int, default=10000, help="Preprocess progress interval; 0 disables")
    parser.add_argument("--slice-log-every", type=int, default=100, help="Print progress every N annotations within a project")
    parser.add_argument(
        "--slice-trace-every",
        type=int,
        default=1,
        help="Print detailed timings every N annotations; 0 disables",
    )
    parser.add_argument(
        "--slice-annotation-timeout-seconds",
        type=int,
        default=0,
        help="Skip an annotation after this many seconds; 0 disables",
    )
    parser.add_argument(
        "--slice-timeout-project",
        action="append",
        default=[],
        help="Apply the annotation timeout only to this owner/repository; repeatable",
    )
    args = parser.parse_args()
    if args.slice_annotation_timeout_seconds < 0:
        parser.error("--slice-annotation-timeout-seconds must be >= 0")
    if args.slice_trace_every < 0:
        parser.error("--slice-trace-every must be >= 0")
    return args


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def stable_number(value: str, seed: int) -> int:
    return int(hashlib.sha1(f"{seed}:{value}".encode("utf-8")).hexdigest()[:16], 16)


def project_from_row(row: dict[str, Any]) -> str:
    file_name = str(row.get("file") or row.get("path") or "").replace("\\", "/")
    parts = [part for part in file_name.split("/") if part]
    if parts and parts[0] == "repos":
        parts = parts[1:]
    if len(parts) < 2:
        raise ValueError(f"Cannot derive owner/repository from {file_name!r}")
    project = f"{parts[0]}/{parts[1]}"
    if not PROJECT_RE.fullmatch(project):
        raise ValueError(f"Unsafe GitHub project name: {project!r}")
    return project


def sample_key(row: dict[str, Any]) -> str:
    return "--".join(str(row.get(key, "")) for key in ("file", "loc", "name", "scope"))


def download_with_resume(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    existing = part.stat().st_size if part.exists() else 0
    request = urllib.request.Request(url, headers={"User-Agent": "TypePro-Kaggle-builder"})
    if existing:
        request.add_header("Range", f"bytes={existing}-")
    with urllib.request.urlopen(request, timeout=60) as response:
        append = existing > 0 and response.status == 206
        mode = "ab" if append else "wb"
        with part.open(mode) as handle:
            shutil.copyfileobj(response, handle, length=1024 * 1024)
    os.replace(part, target)


def ensure_typegen_data(args: argparse.Namespace, work_dir: Path) -> Path:
    archive = Path(args.archive).resolve() if args.archive else work_dir / "downloads" / "typegen-data.zip"
    if not archive.exists():
        print(f"Downloading {TYPEGEN_URL} -> {archive}", flush=True)
        download_with_resume(TYPEGEN_URL, archive)
    if not args.skip_sha256:
        actual = sha256_file(archive)
        if actual != TYPEGEN_SHA256:
            raise ValueError(f"TypeGen archive checksum mismatch: {actual}")
    extracted = work_dir / "typegen_release"
    for member in TYPEGEN_FILES:
        target = extracted / member
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as bundle, bundle.open(member) as source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination)
    return extracted / "data"


def read_json(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, list):
        raise ValueError(f"Expected a JSON list: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False)
    os.replace(temporary, path)


def deduplicate(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        result.setdefault(sample_key(row), row)
    return list(result.values())


def eligible_parameter_rows(rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter]:
    result = []
    stats = Counter()
    for row in rows:
        stats["input"] += 1
        if str(row.get("scope") or "").strip().casefold() != "arg":
            stats["non_parameter"] += 1
            continue
        if is_builtin_annotation(row):
            stats["builtin"] += 1
            continue
        if not str(row.get("gttype") or "").strip():
            stats["missing_ground_truth"] += 1
            continue
        result.append(row)
        stats["eligible"] += 1
    return result, stats


def build_splits(args: argparse.Namespace, data_dir: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    train_raw = read_json(data_dir / "trainset.json")
    test_raw = read_json(data_dir / "testset.json")
    sampled_raw = read_json(data_dir / "testset_randomsampled.json")
    train_source, train_filter = eligible_parameter_rows(train_raw)
    test_source, test_filter = eligible_parameter_rows(test_raw)
    sampled_source, sampled_filter = eligible_parameter_rows(sampled_raw)
    warnings: list[str] = []

    if args.split_profile == "paper_project":
        combined = deduplicate([*train_source, *test_source])
        projects = sorted({project_from_row(row) for row in combined})
        train_projects = {project for project in projects if stable_number(project, args.seed) % 10000 < 7000}
        test_projects_all = set(projects) - train_projects
        ordered_test = sorted(test_projects_all, key=lambda value: stable_number(value, args.seed + 1))
        selected_test = set(ordered_test[: args.test_projects]) if args.test_projects else test_projects_all
        validation_projects = {
            project for project in train_projects
            if stable_number(project, args.seed + 2) % 10000 < int(args.validation_project_ratio * 10000)
        }
        split_rows = {"train": [], "validation": [], "test": []}
        for row in combined:
            project = project_from_row(row)
            if project in validation_projects:
                split_rows["validation"].append(row)
            elif project in train_projects:
                split_rows["train"].append(row)
            elif project in selected_test:
                split_rows["test"].append(row)
        warnings.append(
            "Public TypeGen metadata has no commit_hash. Repositories are checked out at the default-branch HEAD available at build time."
        )
        warnings.append(
            "This is a leakage-free project-level approximation of TypePro's 70/30 protocol; the unreleased processed TypePro split cannot be reproduced byte-for-byte."
        )
    else:
        split_rows = {"train": [], "validation": [], "test": sampled_source}
        train_projects = {project_from_row(row) for row in train_source}
        validation_projects = {
            project for project in train_projects
            if stable_number(project, args.seed + 2) % 10000 < int(args.validation_project_ratio * 10000)
        }
        for row in train_source:
            target = "validation" if project_from_row(row) in validation_projects else "train"
            split_rows[target].append(row)
        overlap = train_projects & {project_from_row(row) for row in sampled_source}
        warnings.append(f"typegen_release preserves its split; {len(overlap)} projects overlap between train and sampled test.")
        warnings.append("Public TypeGen metadata has no commit_hash; repository checkout uses current default-branch HEAD.")

    for split, rows in split_rows.items():
        for row in rows:
            row["split"] = split
            row["language"] = "python"
            project = project_from_row(row)
            row.setdefault("url", f"https://github.com/{project}")

    metadata = {
        "schema_version": SCHEMA_VERSION,
        "split_profile": args.split_profile,
        "seed": args.seed,
        "validation_project_ratio": args.validation_project_ratio,
        "requested_test_projects": args.test_projects,
        "source_counts": {
            "trainset.json": len(train_raw),
            "testset.json": len(test_raw),
            "testset_randomsampled.json": len(sampled_raw),
        },
        "eligibility": {
            "scope": "arg",
            "exclude_builtins": True,
            "positive": "gttype",
            "files": {
                "trainset.json": dict(train_filter),
                "testset.json": dict(test_filter),
                "testset_randomsampled.json": dict(sampled_filter),
            },
        },
        "prepared_counts": {split: len(rows) for split, rows in split_rows.items()},
        "prepared_projects": {
            split: len({project_from_row(row) for row in rows}) for split, rows in split_rows.items()
        },
        "warnings": warnings,
    }
    return split_rows, metadata


def prepare_metadata(args: argparse.Namespace, work_dir: Path) -> dict[str, Any]:
    metadata_dir = work_dir / "metadata"
    split_paths = {split: metadata_dir / f"{split}.json" for split in ("train", "validation", "test")}
    manifest_path = metadata_dir / "split_manifest.json"
    if not args.force_metadata and manifest_path.exists() and all(path.exists() for path in split_paths.values()):
        with manifest_path.open(encoding="utf-8") as handle:
            existing = json.load(handle)
        requested = (SCHEMA_VERSION, args.split_profile, args.seed, args.validation_project_ratio, args.test_projects)
        cached = (
            existing.get("schema_version"), existing.get("split_profile"), existing.get("seed"),
            existing.get("validation_project_ratio"), existing.get("requested_test_projects"),
        )
        if requested != cached:
            raise ValueError(f"Cached split config {cached} != requested {requested}; pass --force-metadata")
        preview_path = metadata_dir / "preview_samples.json"
        previews = json.loads(preview_path.read_text(encoding="utf-8")) if preview_path.exists() else {}
        print_metadata_summary(existing, previews, args)
        return existing
    data_dir = ensure_typegen_data(args, work_dir)
    split_rows, manifest = build_splits(args, data_dir)
    for split, rows in split_rows.items():
        write_json(split_paths[split], rows)
    write_json(manifest_path, manifest)
    previews = {split: rows[: args.preview_samples] for split, rows in split_rows.items()} if args.preview_samples else {}
    write_json(metadata_dir / "preview_samples.json", previews)
    print_metadata_summary(manifest, previews, args)
    return manifest


def print_metadata_summary(
    manifest: dict[str, Any],
    previews: dict[str, list[dict[str, Any]]],
    args: argparse.Namespace,
) -> None:
    summary = {
        "source_records": manifest.get("source_counts", {}),
        "prepared_records": manifest.get("prepared_counts", {}),
        "prepared_projects": manifest.get("prepared_projects", {}),
        "prepared_total": sum(manifest.get("prepared_counts", {}).values()),
    }
    print(f"\n[metadata:full-counts]\n{json.dumps(summary, indent=2, ensure_ascii=False)}", flush=True)
    for split in ("train", "validation", "test"):
        for index, row in enumerate(previews.get(split, [])[: args.preview_samples], start=1):
            print(
                f"\n[metadata:sample] {split} #{index}\n{json_preview(row, args.preview_max_chars)}",
                flush=True,
            )


def run(command: list[str], cwd: Path | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, check=True, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def run_logged(command: list[str], cwd: Path, log_path: Path) -> str:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    tail = ""
    with log_path.open("w", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            log_handle.write(line)
            log_handle.flush()
            tail = (tail + line)[-4000:]
            if line.startswith(("[export:", "[annotation:", "[kb:")):
                tqdm.write(line.rstrip())
        return_code = process.wait()
        if return_code:
            raise subprocess.CalledProcessError(return_code, command, output=tail)
    return tail


def clone_project(project: str, destination: Path) -> str:
    if destination.exists() and (destination / ".git").exists():
        return run(["git", "-C", str(destination), "rev-parse", "HEAD"], capture=True).stdout.strip()
    destination.parent.mkdir(parents=True, exist_ok=True)
    run([
        "git", "clone", "--quiet", "--depth", "1", "--no-tags", "--single-branch",
        f"https://github.com/{project}.git", str(destination),
    ], capture=True)
    return run(["git", "-C", str(destination), "rev-parse", "HEAD"], capture=True).stdout.strip()


def safe_remove_repo(path: Path, allowed_root: Path) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"Refusing to remove path outside repository cache: {resolved}")
    if resolved.exists():
        def remove_readonly(function, target, _error_info):
            os.chmod(target, stat.S_IWRITE)
            function(target)

        shutil.rmtree(resolved, onerror=remove_readonly)


def load_prepared_annotations(work_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split in ("train", "validation", "test"):
        rows.extend(read_json(work_dir / "metadata" / f"{split}.json"))
    return rows


def annotation_timeout_for_project(
    seconds: int, timeout_projects: set[str], project: str
) -> int:
    if seconds <= 0:
        return 0
    if timeout_projects and project not in timeout_projects:
        return 0
    return seconds


def matching_skip_pattern(project: str, patterns: Iterable[str]) -> str | None:
    project_key = project.casefold()
    for pattern in patterns:
        normalized = pattern.strip().casefold()
        if normalized and normalized in project_key:
            return pattern
    return None


def slice_projects(args: argparse.Namespace, work_dir: Path, typepro_root: Path) -> dict[str, Any]:
    python_dir = typepro_root / "Python"
    exporter = python_dir / "export_slices.py"
    kb_builder = python_dir / "build_third_party_kb.py"
    if not exporter.exists():
        raise FileNotFoundError(exporter)
    if args.build_import_kb and not kb_builder.exists():
        raise FileNotFoundError(kb_builder)
    rows_by_project: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in load_prepared_annotations(work_dir):
        rows_by_project[project_from_row(row)].append(row)
    timeout_projects = set(args.slice_timeout_project)
    skip_project_patterns = list(args.skip_project)

    projects = sorted(rows_by_project, key=lambda value: stable_number(value, args.seed + 3))
    projects = [project for project in projects if stable_number(project, args.seed + 4) % args.shard_count == args.shard_index]
    if args.max_projects:
        projects = projects[: args.max_projects]

    raw_dir = work_dir / "raw_slices"
    task_dir = work_dir / "tasks"
    status_dir = work_dir / "project_status"
    generated_kb = work_dir / "third_party_kb" / "dataset"
    # Wheels/extracted sources are transient and intentionally live outside the
    # shard build directory so Kaggle archives only retain compact JSON KB data.
    download_cache = work_dir.parent / f".{work_dir.name}_package_downloads"
    clone_root = Path(args.repos_root).resolve() if args.repos_root else work_dir / "repository_cache"
    for directory in (
        raw_dir, task_dir, status_dir, clone_root, generated_kb, download_cache,
        python_dir / "data", python_dir / "Third-party-data/dataset",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    knowledge_base_paths = []
    if args.build_import_kb:
        knowledge_base_paths.append(generated_kb)
    if args.third_party_kb:
        knowledge_base = Path(args.third_party_kb).resolve()
        if not knowledge_base.is_dir():
            raise FileNotFoundError(knowledge_base)
        knowledge_base_paths.append(knowledge_base)
    if knowledge_base_paths:
        os.environ["TYPEPRO_THIRD_PARTY_DATASET"] = os.pathsep.join(map(str, knowledge_base_paths))
    write_json(work_dir / "runtime_manifest.json", {
        "third_party_knowledge_base_provided": bool(args.third_party_kb),
        "third_party_knowledge_base_path": str(Path(args.third_party_kb).resolve()) if args.third_party_kb else None,
        "import_knowledge_base_built": bool(args.build_import_kb),
        "import_knowledge_base_path": str(generated_kb) if args.build_import_kb else None,
        "download_missing_imports": bool(args.download_missing_imports),
        "repos_root_provided": bool(args.repos_root),
        "slice_annotation_timeout_seconds": args.slice_annotation_timeout_seconds,
        "slice_timeout_projects": sorted(timeout_projects),
        "slice_trace_every": args.slice_trace_every,
        "skip_project_patterns": skip_project_patterns,
        "retrieval_schema_version": args.retrieval_schema_version,
    })

    counters = Counter(selected_projects=len(projects))
    raw_previews_printed = 0
    project_progress = tqdm(
        enumerate(projects, start=1),
        total=len(projects),
        desc=f"TypePro slicing shard {args.shard_index + 1}/{args.shard_count}",
        unit="project",
        dynamic_ncols=True,
        mininterval=1.0,
    )
    for position, project in project_progress:
        slug = project.replace("/", "__")
        output_path = raw_dir / f"{slug}.jsonl"
        status_path = status_dir / f"{slug}.json"
        repository_path = clone_root.joinpath(*project.split("/"))
        project_progress.set_postfix_str(
            f"current={project} annotations={len(rows_by_project[project]):,} "
            f"done={counters['completed_projects']:,} failed={counters['failed_projects']:,}"
        )
        skip_pattern = matching_skip_pattern(project, skip_project_patterns)
        if skip_pattern is not None:
            if output_path.exists():
                output_path.unlink()
            write_json(status_path, {
                "project": project,
                "annotations": len(rows_by_project[project]),
                "exported": 0,
                "failed_annotations": 0,
                "skipped_annotations": len(rows_by_project[project]),
                "skipped": True,
                "skip_pattern": skip_pattern,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            counters["completed_projects"] += 1
            counters["skipped_projects"] += 1
            tqdm.write(
                f"[project:skip] {project} pattern={skip_pattern!r} "
                f"annotations={len(rows_by_project[project]):,}"
            )
            continue
        if output_path.exists() and status_path.exists() and not args.force_projects:
            counters["skipped_complete"] += 1
            if not args.keep_repos and not args.repos_root:
                safe_remove_repo(repository_path, clone_root)
            continue
        tqdm.write(f"[{position}/{len(projects)}] {project} ({len(rows_by_project[project])} annotations)")
        try:
            phase_started = time.monotonic()
            tqdm.write(f"[project:clone:start] {project}")
            commit = clone_project(project, repository_path)
            tqdm.write(
                f"[project:clone:done] {project} seconds={time.monotonic() - phase_started:.1f}"
            )
            kb_summary = None
            if args.build_import_kb:
                phase_started = time.monotonic()
                tqdm.write(f"[project:kb:start] {project}")
                kb_summary_path = status_dir / f"{slug}.kb-summary"
                kb_command = [
                    sys.executable, str(kb_builder),
                    "--project-root", str(repository_path),
                    "--output-dir", str(generated_kb),
                    "--download-cache", str(download_cache),
                    "--max-files-per-package", str(args.kb_max_files_per_package),
                    "--summary-output", str(kb_summary_path),
                ]
                if not args.download_missing_imports:
                    kb_command.append("--no-download-missing")
                run_logged(kb_command, python_dir, status_dir / f"{slug}.kb.log")
                kb_summary = json.loads(kb_summary_path.read_text(encoding="utf-8"))
                tqdm.write(
                    f"[project:kb:done] {project} seconds={time.monotonic() - phase_started:.1f}"
                )
            project_rows = []
            for row in rows_by_project[project]:
                item = dict(row)
                item["source_commit"] = commit
                project_rows.append(item)
            task_path = task_dir / f"{slug}.json"
            write_json(task_path, project_rows)
            temporary_output = output_path.with_suffix(".jsonl.tmp")
            detailed_export_logging = project in timeout_projects
            command = [
                sys.executable, str(exporter), "--dataset", str(task_path),
                "--repos-root", str(clone_root), "--output", str(temporary_output), "--rebuild-index",
                "--parameters-only", "--exclude-builtins",
                "--log-every", str(1 if detailed_export_logging else args.slice_log_every),
                "--trace-every", str(args.slice_trace_every),
            ]
            annotation_timeout = annotation_timeout_for_project(
                args.slice_annotation_timeout_seconds, timeout_projects, project
            )
            if annotation_timeout:
                command.extend([
                    "--annotation-timeout-seconds", str(annotation_timeout)
                ])
            phase_started = time.monotonic()
            tqdm.write(f"[project:export:start] {project}")
            exporter_tail = run_logged(command, python_dir, status_dir / f"{slug}.log")
            tqdm.write(
                f"[project:export:done] {project} seconds={time.monotonic() - phase_started:.1f}"
            )
            os.replace(temporary_output, output_path)
            exported = sum(1 for line in output_path.open(encoding="utf-8") if line.strip())
            status = {
                "project": project,
                "commit": commit,
                "annotations": len(project_rows),
                "exported": exported,
                "failed_annotations": len(project_rows) - exported,
                "annotation_timeout_seconds": annotation_timeout,
                "third_party_kb": kb_summary,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "exporter_tail": exporter_tail,
            }
            write_json(status_path, status)
            counters["completed_projects"] += 1
            counters["exported_records"] += exported
            if raw_previews_printed < args.preview_samples:
                for sample in iter_records(output_path):
                    raw_previews_printed += 1
                    tqdm.write(
                        f"\n[slice:sample] raw #{raw_previews_printed} ({project})\n"
                        f"{json_preview(sample, args.preview_max_chars)}"
                    )
                    if raw_previews_printed >= args.preview_samples:
                        break
            project_progress.set_postfix_str(
                f"current={project} annotations={len(rows_by_project[project]):,} "
                f"done={counters['completed_projects']:,} failed={counters['failed_projects']:,} "
                f"exported={counters['exported_records']:,}"
            )
        except Exception as error:
            counters["failed_projects"] += 1
            write_json(status_path, {
                "project": project,
                "error": f"{type(error).__name__}: {error}",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            tqdm.write(f"FAILED {project}: {error}", file=sys.stderr)
        finally:
            if not args.keep_repos and not args.repos_root:
                safe_remove_repo(repository_path, clone_root)
    all_statuses = []
    for status_path in sorted(status_dir.glob("*.json")):
        with status_path.open(encoding="utf-8") as handle:
            all_statuses.append(json.load(handle))
    counters["status_files_total"] = len(all_statuses)
    counters["completed_projects_total"] = sum("error" not in status for status in all_statuses)
    counters["failed_projects_total"] = sum("error" in status for status in all_statuses)
    counters["skipped_projects_total"] = sum(
        bool(status.get("skipped")) for status in all_statuses
    )
    counters["annotations_total"] = sum(int(status.get("annotations", 0)) for status in all_statuses)
    counters["exported_records_total"] = sum(int(status.get("exported", 0)) for status in all_statuses)
    print(f"\n[slice:full-counts]\n{json.dumps(dict(counters), indent=2, ensure_ascii=False)}", flush=True)
    return dict(counters)


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def git_revision(typepro_root: Path) -> str | None:
    try:
        return run(["git", "-C", str(typepro_root), "rev-parse", "HEAD"], capture=True).stdout.strip()
    except Exception:
        return None


def finalize_dataset(args: argparse.Namespace, work_dir: Path, output_dir: Path, typepro_root: Path) -> dict[str, Any]:
    raw_dir = work_dir / "raw_slices"
    if not any(raw_dir.glob("*.jsonl")):
        raise ValueError(f"No raw slice shards found in {raw_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    preprocess_script = Path(__file__).with_name("preprocess.py")
    command = [
        sys.executable, str(preprocess_script), "--input", str(raw_dir),
        "--output-dir", str(output_dir), "--label-field", "gttype",
        "--max-negatives", str(args.max_negatives), "--missing-positive", args.missing_positive,
        "--missing-positive-eval", "append", "--positive-policy", "ground-truth",
        "--seed", str(args.seed),
        "--preview-samples", str(args.preview_samples),
        "--preview-max-chars", str(args.preview_max_chars),
        "--log-every", str(args.log_every),
    ]
    run(command, cwd=preprocess_script.parent)
    with (work_dir / "metadata" / "split_manifest.json").open(encoding="utf-8") as handle:
        split_manifest = json.load(handle)
    with (output_dir / "preprocess_stats.json").open(encoding="utf-8") as handle:
        preprocess_stats = json.load(handle)
    runtime_manifest_path = work_dir / "runtime_manifest.json"
    runtime_manifest = json.loads(runtime_manifest_path.read_text(encoding="utf-8")) if runtime_manifest_path.exists() else {}
    statuses = []
    for path in sorted((work_dir / "project_status").glob("*.json")):
        with path.open(encoding="utf-8") as handle:
            statuses.append(json.load(handle))
    failures = [status for status in statuses if "error" in status]
    expected_projects = set()
    for split in ("train", "validation", "test"):
        expected_projects.update(project_from_row(row) for row in read_json(work_dir / "metadata" / f"{split}.json"))
    completed_projects = {status["project"] for status in statuses if "error" not in status}
    missing_projects = sorted(expected_projects - {status.get("project") for status in statuses})
    if not args.allow_partial and missing_projects:
        raise ValueError(
            f"Dataset is incomplete: {len(missing_projects)} projects were not attempted. "
            "Rerun --stage slice to resume, or pass --allow-partial explicitly."
        )
    if args.strict_projects and failures:
        raise ValueError(f"Dataset has {len(failures)} failed repositories and --strict-projects was requested")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "language": "python",
        "source": {
            "typegen_url": TYPEGEN_URL,
            "typegen_sha256": TYPEGEN_SHA256,
            "typepro_git_revision": git_revision(typepro_root),
            "repository_revision_policy": "source_commit from metadata when present; otherwise default-branch HEAD at build time",
        },
        "split": split_manifest,
        "preprocessing": {
            "max_negatives": args.max_negatives,
            "positive_policy": "ground-truth",
            "positive_field": "gttype",
            "scope": "arg",
            "exclude_builtins": True,
            "stats": preprocess_stats,
            "third_party_knowledge_base_provided": bool(runtime_manifest.get("third_party_knowledge_base_provided")),
            "import_knowledge_base_built": bool(runtime_manifest.get("import_knowledge_base_built")),
            "download_missing_imports": bool(runtime_manifest.get("download_missing_imports")),
        },
        "output": {
            split: {
                "file": f"{split}.jsonl",
                "rows": count_jsonl(output_dir / f"{split}.jsonl"),
                "sha256": sha256_file(output_dir / f"{split}.jsonl"),
            }
            for split in ("train", "validation", "test")
        },
        "projects": {
            "status_files": len(statuses),
            "completed": len(statuses) - len(failures),
            "failed": len(failures),
            "expected": len(expected_projects),
            "missing": missing_projects,
            "failures": failures,
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    card = f"""# TypePro CodeT5+ contrastive dataset

Generated once by `prepare_dataset.py`; fine-tuning must consume these immutable files directly.

- schema: `{SCHEMA_VERSION}`
- language: Python
- target scope: function parameters only
- positive: `gttype`
- built-in annotations: excluded
- third-party recommendations: structural definitions built from project imports
- split profile: `{split_manifest['split_profile']}`
- train rows: {manifest['output']['train']['rows']}
- validation rows: {manifest['output']['validation']['rows']}
- test rows: {manifest['output']['test']['rows']}
- failed repositories: {len(failures)}

See `manifest.json` and `preprocess_stats.json` for provenance, checksums, and candidate recall counts.
"""
    (output_dir / "DATASET_CARD.md").write_text(card, encoding="utf-8")
    final_counts = {
        "prepared_records": split_manifest.get("prepared_counts", {}),
        "processed_records": {split: manifest["output"][split]["rows"] for split in ("train", "validation", "test")},
        "processed_total": sum(manifest["output"][split]["rows"] for split in ("train", "validation", "test")),
        "projects": {
            key: manifest["projects"][key]
            for key in ("expected", "completed", "failed")
        },
    }
    print(f"\n[dataset:full-counts]\n{json.dumps(final_counts, indent=2, ensure_ascii=False)}", flush=True)
    for split in ("train", "validation", "test"):
        print_jsonl_samples(
            output_dir / f"{split}.jsonl",
            args.preview_samples,
            args.preview_max_chars,
            title=f"final {split}",
        )
    return manifest


def main() -> None:
    args = parse_args()
    if args.shard_count <= 0 or not 0 <= args.shard_index < args.shard_count:
        raise ValueError("Require 0 <= shard-index < shard-count")
    if not 0 <= args.validation_project_ratio < 1:
        raise ValueError("validation-project-ratio must be in [0, 1)")
    work_dir = Path(args.work_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    typepro_root = Path(args.typepro_root).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    if args.stage in {"all", "metadata"}:
        manifest = prepare_metadata(args, work_dir)
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    elif not (work_dir / "metadata" / "split_manifest.json").exists():
        raise FileNotFoundError("Run --stage metadata first")

    if args.stage in {"all", "slice"}:
        result = slice_projects(args, work_dir, typepro_root)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    if args.stage in {"all", "finalize"}:
        manifest = finalize_dataset(args, work_dir, output_dir, typepro_root)
        print(json.dumps(manifest["output"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
