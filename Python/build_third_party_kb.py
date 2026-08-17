"""Build TypePro third-party JSON records from imports used by one project.

The scanner never imports a discovered package.  It locates installed source
or downloads a wheel without dependencies, then parses ``.py``/``.pyi`` files
with ``ast``.  The resulting JSON is compatible with ``import_analyzer.py``
and also carries a richer structural definition for recommendation models.
"""
from __future__ import annotations

import argparse
import ast
import importlib.machinery
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


SKIP_DIRECTORIES = {
    ".git", ".hg", ".mypy_cache", ".pytest_cache", ".tox", ".venv",
    "__pycache__", "build", "dist", "node_modules", "venv",
}
IMPORT_TO_DISTRIBUTION = {
    "Crypto": "pycryptodome",
    "OpenSSL": "pyOpenSSL",
    "PIL": "Pillow",
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "googleapiclient": "google-api-python-client",
    "jwt": "PyJWT",
    "mysql": "mysql-connector-python",
    "sklearn": "scikit-learn",
    "telegram": "python-telegram-bot",
    "yaml": "PyYAML",
}
USEFUL_DUNDERS = {"__call__", "__enter__", "__exit__", "__getitem__", "__init__", "__iter__", "__len__"}
KB_SCHEMA_VERSION = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a TypePro KB for imports used by a project")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--download-cache", required=True)
    parser.add_argument("--download-missing", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--reuse-existing", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-files-per-package", type=int, default=3000)
    parser.add_argument("--max-members-per-class", type=int, default=80)
    parser.add_argument("--max-definition-chars", type=int, default=16000)
    parser.add_argument("--summary-output")
    parser.add_argument(
        "--typeshed-root", action="append", default=[],
        help="Optional Typeshed/stub root; repeat or set TYPEPRO_TYPESHED_PATH",
    )
    return parser.parse_args()


def iter_python_files(root: Path) -> Iterable[Path]:
    for directory, names, files in os.walk(root):
        names[:] = [name for name in names if name not in SKIP_DIRECTORIES and not name.startswith(".")]
        base = Path(directory)
        for name in files:
            if name.endswith((".py", ".pyi")):
                yield base / name


def discover_imports(project_root: Path) -> tuple[set[str], Counter[str]]:
    imports: set[str] = set()
    failures: Counter[str] = Counter()
    for path in iter_python_files(project_root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        except (OSError, SyntaxError, ValueError):
            failures["project_parse_failures"] += 1
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.add(node.module.split(".", 1)[0])
    return imports, failures


def local_module_names(project_root: Path) -> set[str]:
    names = {path.stem for path in project_root.glob("*.py")}
    for base in (project_root, project_root / "src"):
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if child.is_dir() and (child / "__init__.py").exists():
                names.add(child.name)
            elif child.suffix == ".py":
                names.add(child.stem)
    return names


def installed_roots(import_name: str) -> list[Path]:
    try:
        spec = importlib.machinery.PathFinder.find_spec(import_name)
    except (ImportError, AttributeError, ValueError):
        return []
    if spec is None or spec.origin in {None, "built-in", "frozen"}:
        return []
    if spec.submodule_search_locations:
        return [Path(value).resolve() for value in spec.submodule_search_locations if Path(value).exists()]
    origin = Path(spec.origin)
    return [origin.resolve()] if origin.suffix in {".py", ".pyi"} and origin.exists() else []


def typeshed_roots(import_name: str, configured: Iterable[str]) -> list[Path]:
    """Locate stdlib or third-party stub packages without importing them."""
    roots = []
    for value in configured:
        base = Path(value).expanduser()
        if not base.is_dir():
            continue
        candidates = [
            base / "stdlib" / f"{import_name}.pyi",
            base / "stdlib" / import_name,
            base / f"{import_name}.pyi",
            base / import_name,
        ]
        stubs = base / "stubs"
        if stubs.is_dir():
            candidates.extend(stubs.glob(f"*/{import_name}.pyi"))
            candidates.extend(stubs.glob(f"*/{import_name}"))
        roots.extend(path.resolve() for path in candidates if path.exists())
    return list(dict.fromkeys(roots))


def bundled_typeshed_paths() -> list[str]:
    """Discover Typeshed bundled by typeshed-client when installed."""
    try:
        spec = importlib.machinery.PathFinder.find_spec("typeshed_client")
    except (ImportError, AttributeError, ValueError):
        return []
    if spec is None:
        return []
    locations = list(spec.submodule_search_locations or ())
    if spec.origin:
        locations.append(str(Path(spec.origin).parent))
    results = []
    for location in locations:
        candidate = Path(location) / "typeshed"
        if candidate.is_dir():
            results.append(str(candidate.resolve()))
    return list(dict.fromkeys(results))


def safe_extract_wheel(wheel: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(wheel) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"Unsafe wheel member: {member.filename}")
        bundle.extractall(destination)


def download_roots(import_name: str, cache: Path) -> list[Path]:
    installed_distributions = importlib.metadata.packages_distributions().get(
        import_name, []
    )
    distribution = IMPORT_TO_DISTRIBUTION.get(
        import_name, installed_distributions[0] if installed_distributions else import_name
    )
    destination = cache / distribution.casefold().replace("-", "_")
    extracted = destination / "extracted"
    if not extracted.exists():
        wheels = sorted(destination.glob("*.whl")) if destination.exists() else []
        if not wheels and not list(destination.glob("*.tar.gz")) and not list(destination.glob("*.zip")):
            destination.mkdir(parents=True, exist_ok=True)
            wheel_command = [
                sys.executable, "-m", "pip", "download", "--disable-pip-version-check",
                "--no-deps", "--only-binary=:all:", "--dest", str(destination), distribution,
            ]
            wheel_result = subprocess.run(
                wheel_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            if wheel_result.returncode:
                source_command = [
                    sys.executable, "-m", "pip", "download", "--disable-pip-version-check",
                    "--no-deps", "--no-binary=:all:", "--dest", str(destination), distribution,
                ]
                subprocess.run(
                    source_command, check=True, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True,
                )
            wheels = sorted(destination.glob("*.whl"))
        archives = [*wheels, *sorted(destination.glob("*.tar.gz")), *sorted(destination.glob("*.zip"))]
        if not archives:
            return []
        temporary = destination / "extracted.tmp"
        if temporary.exists():
            shutil.rmtree(temporary)
        archive = archives[-1]
        if archive.suffix == ".whl" or archive.suffix == ".zip":
            safe_extract_wheel(archive, temporary)
        else:
            safe_extract_tar(archive, temporary)
        os.replace(temporary, extracted)
    candidates = [
        extracted / import_name,
        extracted / f"{import_name}.py",
        extracted / "src" / import_name,
        extracted / "src" / f"{import_name}.py",
    ]
    candidates.extend(extracted.glob(f"*/{import_name}"))
    candidates.extend(extracted.glob(f"*/src/{import_name}"))
    return [path.resolve() for path in candidates if path.exists()]


def safe_extract_tar(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive) as bundle:
        members = []
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"Unsafe source archive member: {member.name}")
            if member.issym() or member.islnk():
                raise ValueError(f"Links are not allowed in source archives: {member.name}")
            if not member.isfile() and not member.isdir():
                raise ValueError(f"Unsupported source archive member: {member.name}")
            members.append(member)
        bundle.extractall(destination, members=members)


def unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def module_name(import_name: str, root: Path, source: Path) -> str:
    if root.is_file():
        return import_name
    relative = source.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join([import_name, *parts]) if parts else import_name


def function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {unparse(node.returns)}" if node.returns is not None else ""
    return f"{prefix} {node.name}({unparse(node.args)}){returns}:"


def class_definition(
    node: ast.ClassDef,
    *,
    package: str,
    module: str,
    max_members: int,
    max_chars: int,
    source_kind: str = "third_party",
) -> tuple[str, list[str], list[str], list[str]]:
    bases = [unparse(value) for value in node.bases]
    bases.extend(f"{keyword.arg}={unparse(keyword.value)}" for keyword in node.keywords if keyword.arg)
    header = f"class {node.name}({', '.join(value for value in bases if value)}):" if bases else f"class {node.name}:"
    lines = [
        header,
        f"    # package: {package}",
        f"    # module: {module}",
        f"    # source: {source_kind}",
    ]
    fields: list[str] = []
    methods: list[str] = []
    decorators = [unparse(value) for value in node.decorator_list]
    for statement in node.body:
        if len(fields) + len(methods) >= max_members:
            break
        if isinstance(statement, ast.AnnAssign):
            name = unparse(statement.target)
            if name and not name.startswith("_"):
                value = f" = {unparse(statement.value)}" if statement.value is not None else ""
                fields.append(f"{name}: {unparse(statement.annotation)}{value}")
        elif isinstance(statement, ast.Assign):
            names = [unparse(target) for target in statement.targets]
            names = [name for name in names if name and not name.startswith("_")]
            if names:
                fields.append(f"{' = '.join(names)} = {unparse(statement.value)}")
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not statement.name.startswith("_") or statement.name in USEFUL_DUNDERS:
                methods.append(function_signature(statement))
    if decorators:
        lines[0:0] = [f"@{value}" for value in decorators if value]
    if fields:
        lines.append("    # fields")
        lines.extend(f"    {value}" for value in fields)
    if methods:
        lines.append("    # public methods")
        lines.extend(f"    {value}" for value in methods)
    if not fields and not methods:
        lines.append("    pass")
    definition = "\n".join(lines)
    if len(definition) > max_chars:
        definition = definition[:max_chars].rsplit("\n", 1)[0] + "\n    # ... truncated"
    return definition, fields, methods, bases


def scan_package(
    import_name: str,
    roots: list[Path],
    *,
    max_files: int,
    max_members: int,
    max_chars: int,
    source_kind: str = "third_party",
) -> tuple[list[dict[str, Any]], Counter[str]]:
    records: dict[tuple[str, str, str], dict[str, Any]] = {}
    stats: Counter[str] = Counter()
    sources: list[tuple[Path, Path]] = []
    for root in roots:
        if root.is_file():
            sources.append((root, root))
        else:
            sources.extend((root, path) for path in iter_python_files(root))
    # Stub declarations are generally more useful for type retrieval.
    sources.sort(key=lambda item: (item[1].suffix != ".pyi", str(item[1])))
    for root, source in sources[:max_files]:
        stats["files_scanned"] += 1
        try:
            tree = ast.parse(source.read_text(encoding="utf-8", errors="replace"), filename=str(source))
        except (OSError, SyntaxError, ValueError):
            stats["parse_failures"] += 1
            continue
        module = module_name(import_name, root, source)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                definition, fields, methods, bases = class_definition(
                    node, package=import_name, module=module,
                    max_members=max_members, max_chars=max_chars,
                    source_kind=source_kind,
                )
                record = {
                    "kb_schema_version": KB_SCHEMA_VERSION,
                    "type": "class",
                    "name": node.name,
                    "package": import_name,
                    "module": module,
                    "qualified_name": f"{module}.{node.name}",
                    "bases": bases,
                    "fields": fields,
                    "methods": methods,
                    "definition": definition,
                    "source": source_kind,
                    "kind": "class",
                }
                key = ("class", node.name, module)
                previous = records.get(key)
                if previous is None or len(definition) > len(previous["definition"]):
                    records[key] = record
                if node.name.startswith("_"):
                    stats["private_classes"] += 1
            elif (alias := type_alias(node)) is not None:
                name, value = alias
                definition = "\n".join([
                    f"class {name}:",
                    f"    # package: {import_name}",
                    f"    # module: {module}",
                    f"    # source: {source_kind}",
                    "    # kind: alias",
                    f"    # type alias: {value}",
                ])
                records.setdefault(("alias", name, module), {
                    "kb_schema_version": KB_SCHEMA_VERSION,
                    "type": "class",
                    "kind": "alias",
                    "name": name,
                    "package": import_name,
                    "module": module,
                    "qualified_name": f"{module}.{name}",
                    "bases": [],
                    "fields": [f"type alias = {value}"],
                    "methods": [],
                    "definition": definition,
                    "source": source_kind,
                })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                signature = function_signature(node)
                records.setdefault(("function", node.name, module), {
                    "kb_schema_version": KB_SCHEMA_VERSION,
                    "type": "function",
                    "name": node.name,
                    "package": import_name,
                    "module": module,
                    "qualified_name": f"{module}.{node.name}",
                    "signature": signature,
                })
    stats["files_skipped_by_limit"] = max(0, len(sources) - max_files)
    stats["classes"] = sum(item[0] == "class" for item in records)
    stats["aliases"] = sum(item[0] == "alias" for item in records)
    stats["functions"] = sum(item[0] == "function" for item in records)
    return list(records.values()), stats


def type_alias(node: ast.AST) -> tuple[str, str] | None:
    target = value = annotation = None
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        target, value, annotation = node.target.id, node.value, unparse(node.annotation)
    elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        target, value = node.targets[0].id, node.value
    if not target or value is None:
        return None
    type_like_name = target.lstrip("_")[:1].isupper()
    explicit_alias = bool(annotation and annotation.endswith("TypeAlias"))
    recognized = explicit_alias or (
        type_like_name and isinstance(value, (ast.Subscript, ast.Attribute, ast.BinOp))
    )
    if isinstance(value, ast.Call):
        call_name = unparse(value.func).split(".")[-1]
        recognized = type_like_name and call_name in {
            "NewType", "TypeVar", "ParamSpec", "TypeVarTuple"
        }
    if isinstance(value, ast.Name):
        recognized = explicit_alias
    return (target, unparse(value)) if recognized else None


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def main() -> None:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    cache = Path(args.download_cache).resolve()
    configured_typeshed = [
        *args.typeshed_root,
        *(value for value in os.environ.get("TYPEPRO_TYPESHED_PATH", "").split(os.pathsep) if value),
        *bundled_typeshed_paths(),
    ]
    imports, discovery_stats = discover_imports(project_root)
    local_modules = local_module_names(project_root)
    stdlib = sorted(name for name in imports if name in sys.stdlib_module_names)
    third_party = sorted(
        name for name in imports
        if name and name not in sys.stdlib_module_names and name not in local_modules
    )
    summary: dict[str, Any] = {
        "project_root": str(project_root),
        "imports_discovered": len(imports),
        "third_party_imports": third_party,
        "stdlib_imports": stdlib,
        "packages": {},
        **discovery_stats,
    }
    for import_name in [*stdlib, *third_party]:
        output_path = output_dir / f"{import_name}.json"
        if args.reuse_existing and output_path.exists():
            try:
                existing = json.loads(output_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = None
            if (
                isinstance(existing, list)
                and bool(existing)
                and all(
                    isinstance(item, dict)
                    and item.get("kb_schema_version") == KB_SCHEMA_VERSION
                    for item in existing
                )
            ):
                summary["packages"][import_name] = {"status": "reused", "records": len(existing)}
                continue
        stub_roots = typeshed_roots(import_name, configured_typeshed)
        roots = installed_roots(import_name)
        source = "installed"
        error = None
        is_stdlib = import_name in sys.stdlib_module_names
        if not roots and args.download_missing and not is_stdlib:
            source = "downloaded-archive"
            try:
                roots = download_roots(import_name, cache)
            except (OSError, subprocess.CalledProcessError, zipfile.BadZipFile, ValueError) as exception:
                error = f"{type(exception).__name__}: {exception}"
        if not roots and not stub_roots:
            summary["packages"][import_name] = {"status": "unresolved", "error": error}
            continue
        records = []
        stats: Counter[str] = Counter()
        if roots:
            runtime_records, runtime_stats = scan_package(
                import_name, roots,
                max_files=args.max_files_per_package,
                max_members=args.max_members_per_class,
                max_chars=args.max_definition_chars,
                source_kind="stdlib" if is_stdlib else "third_party",
            )
            records.extend(runtime_records)
            stats.update(runtime_stats)
        if stub_roots:
            stub_records, stub_stats = scan_package(
                import_name, stub_roots,
                max_files=args.max_files_per_package,
                max_members=args.max_members_per_class,
                max_chars=args.max_definition_chars,
                source_kind="typeshed",
            )
            # Stubs carry the authoritative public API, so replace an
            # equivalent runtime record while retaining runtime-only symbols.
            keyed = {
                (item["type"], item["name"], item.get("module", "")): item
                for item in records
            }
            keyed.update({
                (item["type"], item["name"], item.get("module", "")): item
                for item in stub_records
            })
            records = list(keyed.values())
            stats.update(stub_stats)
            stats["typeshed_records"] = len(stub_records)
        write_json(output_path, records)
        summary["packages"][import_name] = {
            "status": "written", "source": source,
            "typeshed_roots": len(stub_roots), "records": len(records), **stats,
        }
    summary["packages_written"] = sum(item.get("status") in {"written", "reused"} for item in summary["packages"].values())
    summary["packages_unresolved"] = sum(item.get("status") == "unresolved" for item in summary["packages"].values())
    summary["stdlib_packages_written"] = sum(
        name in sys.stdlib_module_names and item.get("status") in {"written", "reused"}
        for name, item in summary["packages"].items()
    )
    if args.summary_output:
        write_json(Path(args.summary_output), summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
