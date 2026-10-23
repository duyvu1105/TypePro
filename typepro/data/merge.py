from __future__ import annotations

if __package__ in (None, ''):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge resumable TypePro build shards")
    parser.add_argument("--shard-build-dirs", nargs="+", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument('--expected-retrieval-schema')
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def copy_checked(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256(source) != sha256(destination):
            raise ValueError(f"Conflicting shard file: {destination.name}")
        return
    shutil.copy2(source, destination)


def locate_build_dir(path: Path) -> Path:
    if (path / "metadata" / "split_manifest.json").exists():
        return path
    candidates = list(path.rglob("metadata/split_manifest.json"))
    if len(candidates) != 1:
        raise ValueError(f"Cannot uniquely locate typepro_build below {path}: {len(candidates)} matches")
    return candidates[0].parent.parent


def main() -> None:
    from typepro.analysis.candidate_policy import (
        SUPPORTED_POLICIES, DEFINITION_CHARS, TOTAL_CHARS, candidate_section,
    )
    args = parse_args()
    destination = Path(args.work_dir).resolve()
    builds = [locate_build_dir(Path(value).resolve()) for value in args.shard_build_dirs]
    policies = {json.loads((build / 'runtime_manifest.json').read_text(encoding='utf-8'))
                .get('candidate_policy_version') for build in builds}
    if len(policies) != 1:
        raise ValueError('Shard candidate policies differ; rebuild with one policy before merging')
    runtime_policy = next(iter(policies))
    for build in builds:
        for raw_file in (build / 'raw_slices').glob('*.jsonl'):
            with raw_file.open(encoding='utf-8') as handle:
                for line in handle:
                    if line.strip() and json.loads(line).get('candidate_policy_version') != runtime_policy:
                        raise ValueError(f'Candidate policy differs from runtime: {raw_file}')
    if args.expected_retrieval_schema:
        for build in builds:
            runtime = json.loads((build / 'runtime_manifest.json').read_text(encoding='utf-8'))
            if runtime.get('retrieval_schema_version') != args.expected_retrieval_schema:
                raise ValueError(f'Incompatible retrieval schema: {build}')
            if runtime.get('context_policy_version') != 'ast-context-v8-type-evidence-stop':
                raise ValueError(f'Incompatible context policy: {build}')
            for raw_file in (build / 'raw_slices').glob('*.jsonl'):
                with raw_file.open(encoding='utf-8') as handle:
                    for line in handle:
                        if line.strip():
                            row = json.loads(line)
                            if row.get('target_masking_version') != 'typepro-shared-kb-masked-source-v7-resolved-bounded-context' or row.get('context_policy_version') != 'ast-context-v8-type-evidence-stop':
                                raise ValueError(f'Unmasked legacy record or incompatible context policy: {raw_file}')
                            maximum = DEFINITION_CHARS if row.get('candidate_policy_version') in SUPPORTED_POLICIES else 8000
                            if row.get('candidate_definition_max_chars') != maximum or any(len(str(item.get('definition') or '')) > maximum for item in row.get('recommendation_types', [])):
                                raise ValueError(f'Unbounded candidate definition: {raw_file}')
                            if maximum == DEFINITION_CHARS and len(candidate_section(row.get('recommendation_types', []))) > TOTAL_CHARS:
                                raise ValueError(f'Unbounded candidate section: {raw_file}')
    reference_manifest = None
    reference_lock = None
    copied = {"raw_slices": 0, "project_status": 0, "project_kb": 0}
    for build in builds:
        manifest_path = build / "metadata" / "split_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        runtime_path = build / "runtime_manifest.json"
        runtime_value = json.loads(runtime_path.read_text(encoding="utf-8"))
        lock_identity = (
            runtime_value.get("project_revision_lock_sha256"),
            runtime_value.get("revision_lock_source"),
            runtime_value.get("revision_lock_policy"),
        )
        if reference_lock is None:
            reference_lock = lock_identity
        elif lock_identity != reference_lock:
            raise ValueError(f"Shard project revision locks differ: {build}")
        if reference_manifest is None:
            reference_manifest = manifest
            for metadata_file in (build / "metadata").glob("*.json"):
                copy_checked(metadata_file, destination / "metadata" / metadata_file.name)
            runtime = build / "runtime_manifest.json"
            if runtime.exists():
                copy_checked(runtime, destination / runtime.name)
        elif manifest != reference_manifest:
            raise ValueError(f"Shard split manifest differs: {build}")

        for directory, pattern in (
            ("raw_slices", "*.jsonl"), ("project_status", "*.json"),
            ("project_status", "*.log"), ("project_kb", "*/knowledge_base.json"),
        ):
            for source in (build / directory).glob(pattern):
                relative = source.relative_to(build / directory)
                copy_checked(source, destination / directory / relative)
                copied[directory] += 1
    print(json.dumps({"merged_builds": [str(path) for path in builds], **copied}, indent=2))


if __name__ == "__main__":
    main()
