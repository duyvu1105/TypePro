"""Reuse a frozen project KB, never old slices or source-analysis indexes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import zipfile

from typepro.analysis.project_kb import SCHEMA_VERSION


def attached_build(input_root: Path, destination: Path, index: int, count: int) -> Path | None:
    """Read only the attached partition; extract KB/status metadata, not raw rows."""
    if not input_root.exists():
        return None
    markers = list(input_root.rglob('shard_manifest.json'))
    if not markers:
        archives = list(input_root.rglob(f'typepro_build_shard_{index:02d}.zip'))
        if len(archives) != 1:
            return None
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archives[0]) as bundle:
            for member in bundle.infolist():
                relative = Path(member.filename)
                if relative.is_absolute() or '..' in relative.parts or '\\' in member.filename:
                    raise ValueError('Unsafe attached shard archive path')
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise ValueError('Attached shard archive contains a symlink')
                parts = relative.parts
                roots = {'project_kb', 'project_status', 'runtime_manifest.json', 'shard_manifest.json'}
                if not any(part in roots for part in parts):
                    continue
                if not member.is_dir() and relative.suffix == '.json':
                    target = destination / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(member) as source, target.open('wb') as out:
                        shutil.copyfileobj(source, out)
        markers = list(destination.rglob('shard_manifest.json'))
    if len(markers) != 1:
        raise ValueError('Expected one attached shard manifest')
    manifest = json.loads(markers[0].read_text())
    if (manifest.get('shard_index'), manifest.get('shard_count')) != (index, count):
        raise ValueError('Attached KB shard coordinates do not match this notebook')
    if manifest.get('missing_projects') != []:
        raise ValueError('Attached KB shard is incomplete')
    return markers[0].parent


def reuse_project_kb(source_build: Path | None, project: str, commit: str,
                     destination: Path, retrieval_schema: str) -> dict | None:
    """Validate frozen provenance and materialize an isolated import index.

    Published shards retain the complete KB but omit transient package JSONs.
    Recreate those JSONs from stored package records; do not download newer
    dependency versions or change the frozen candidate pool.
    """
    if source_build is None:
        return None
    root = source_build.resolve()
    slug = project.replace('/', '__')
    if not re.fullmatch(r'[\w.-]+__[\w.-]+', slug):
        raise ValueError('Invalid project name for KB reuse')
    kb_path = root / 'project_kb' / slug / 'knowledge_base.json'
    status_path = root / 'project_status' / (slug + '.json')
    runtime_path = root / 'runtime_manifest.json'
    if not all(p.is_file() for p in (kb_path, status_path, runtime_path)):
        return None
    for path in (kb_path, status_path, runtime_path):
        if not path.resolve().is_relative_to(root):
            raise ValueError('KB provenance path escapes source build')
    status = json.loads(status_path.read_text())
    runtime = json.loads(runtime_path.read_text())
    if (status.get('project') != project or status.get('commit') != commit
            or runtime.get('retrieval_schema_version') != retrieval_schema
            or status.get('retrieval_schema_version') != retrieval_schema
            or runtime.get('context_policy_version') != 'ast-context-v7-verified-signature-evidence'):
        return None
    payload = kb_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    recorded_digest = (status.get('project_kb') or {}).get('sha256')
    if recorded_digest and recorded_digest != digest:
        raise ValueError('Frozen KB checksum differs from recorded project status')
    kb = json.loads(payload)
    if kb.get('schema_version') != SCHEMA_VERSION:
        return None
    records = kb.get('records')
    if not isinstance(records, list) or kb.get('record_count') != len(records):
        raise ValueError('Invalid frozen KB records/count')
    packages = {}
    for item in records:
        if not isinstance(item, dict):
            raise ValueError('Invalid frozen KB record')
        if item.get('source') == 'project' or item.get('type') not in {'class', 'function'}:
            continue
        package = item.get('package', '')
        if not isinstance(package, str) or not package.isidentifier():
            # Without package provenance, recreating the old import index is
            # unsafe. Rebuild this project normally instead.
            return None
        if item.get('type') == 'function' and not isinstance(item.get('signature'), str):
            return None
        packages.setdefault(package, []).append(item)
    destination.mkdir(parents=True, exist_ok=True)
    imports = destination / 'imports'
    if imports.exists():
        shutil.rmtree(imports)
    imports.mkdir()
    for package, values in packages.items():
        (imports / (package + '.json')).write_text(json.dumps(values, ensure_ascii=False))
    (destination / 'knowledge_base.json').write_bytes(payload)
    return dict(reused=True, source_build=str(root), source_commit=commit,
                schema_version=SCHEMA_VERSION, sha256=digest,
                import_packages=len(packages), records=len(records))
