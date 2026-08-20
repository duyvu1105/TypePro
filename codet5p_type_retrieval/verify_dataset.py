from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a cached TypePro Kaggle Dataset")
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()
    root = Path(args.data_dir)
    with (root / "manifest.json").open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    errors = []
    kb_key_cache: dict[Path, set[str]] = {}
    kb_root = root / "project_kb"
    kb_available = kb_root.is_dir()
    if not kb_available:
        print("project_kb is absent; skipping project KB cross-checks", flush=True)
    if manifest.get("schema_version") != "typepro-codet5p-generative-project-kb-v1":
        errors.append(f"unexpected schema: {manifest.get('schema_version')!r}")
    for split, expected in manifest["output"].items():
        path = root / expected["file"]
        if not path.exists():
            errors.append(f"missing {path}")
            continue
        actual_hash = sha256(path)
        actual_rows = sum(1 for line in path.open(encoding="utf-8") if line.strip())
        if actual_hash != expected["sha256"]:
            errors.append(f"{split}: sha256 mismatch")
        if actual_rows != expected["rows"]:
            errors.append(f"{split}: row count {actual_rows} != {expected['rows']}")
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                required = {
                    "target_name", "target_function", "interprocedural_slice",
                    "recommendation_types", "input", "label", "project",
                }
                missing = required - row.keys()
                if missing:
                    errors.append(f"{split}:{line_number}: missing fields {sorted(missing)}")
                    break
                if not 1 <= len(row["recommendation_types"]) <= 10:
                    errors.append(f"{split}:{line_number}: recommendation count is not 1..10")
                    break
                if any(
                    not item.get("type") or not item.get("definition")
                    for item in row["recommendation_types"]
                ):
                    errors.append(f"{split}:{line_number}: invalid recommendation entry")
                    break
                if not all(tag in row["input"] for tag in (
                    "[TARGET_NAME]", "[TARGET_FUNCTION]", "[INTERPROCEDURAL_SLICE]",
                    "[RECOMMENDATION_TYPES]", "[TYPE]", "[DEFINITION]",
                )):
                    errors.append(f"{split}:{line_number}: tagged input is incomplete")
                    break
                if kb_available:
                    kb_path = (
                        kb_root /
                        str(row["project"]).replace("/", "__") /
                        "knowledge_base.json"
                    )
                    if not kb_path.exists():
                        errors.append(f"{split}:{line_number}: missing project KB {kb_path}")
                        break
                    if kb_path not in kb_key_cache:
                        kb = json.loads(kb_path.read_text(encoding="utf-8"))
                        kb_key_cache[kb_path] = {
                            str(item.get("qualified_name") or item.get("name") or "").casefold()
                            for item in kb.get("records", []) if isinstance(item, dict)
                        }
                    kb_keys = kb_key_cache[kb_path]
                    outside = [
                        item.get("qualified_name") or item.get("type")
                        for item in row["recommendation_types"]
                        if str(item.get("qualified_name") or item.get("type") or "").casefold()
                        not in kb_keys
                    ]
                    if outside:
                        errors.append(
                            f"{split}:{line_number}: recommendations outside project KB {outside}"
                        )
                        break
    if kb_available:
        kb_files = list(kb_root.glob("*/knowledge_base.json"))
        expected_kbs = manifest.get("projects", {}).get("knowledge_bases")
        if not kb_files or expected_kbs != len(kb_files):
            errors.append(
                f"project KB count {len(kb_files)} != manifest {expected_kbs!r}"
            )
    if errors:
        raise SystemExit("Dataset verification failed:\n- " + "\n- ".join(errors))
    print(json.dumps({"verified": True, "schema": manifest["schema_version"], "output": manifest["output"]}, indent=2))
