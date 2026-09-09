"""Build a deterministic project-to-commit lock from finalized JSONL splits."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--dataset-version", type=int, required=True)
    args = parser.parse_args()

    projects: dict[str, str] = {}
    spellings: dict[str, str] = {}
    for split in ("train", "validation", "test"):
        with (args.data_dir / f"{split}.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                project = str(row["project"])
                commit = str(row.get("source_commit") or "").strip().lower()
                if not re.fullmatch(r"[0-9a-f]{40}", commit):
                    raise ValueError(f"Missing/invalid source_commit for {project}")
                key = project.casefold()
                if key in projects and projects[key] != commit:
                    raise ValueError(f"Multiple commits for {project}: {projects[key]} and {commit}")
                projects[key] = commit
                spellings.setdefault(key, project)

    payload = {
        "schema_version": "typepro-project-revision-lock-v1",
        "source": {"dataset": args.dataset, "version": args.dataset_version},
        "projects": {spellings[key]: projects[key] for key in sorted(projects)},
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "projects": len(projects)}))


if __name__ == "__main__":
    main()
