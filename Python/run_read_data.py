"""Compatibility entry point for the unified project index builder."""
import json
import sys
from pathlib import Path

from project_index import build_project_index


if len(sys.argv) != 2:
    raise SystemExit("usage: run_read_data.py PROJECT_ROOT")

summary = build_project_index(Path(sys.argv[1]).resolve(), Path("data"))
print(json.dumps(summary, sort_keys=True), flush=True)
