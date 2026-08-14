from __future__ import annotations

import hashlib
import json
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SPECIAL_TOKENS = [
    "[LANGUAGE]",
    "[TARGET_KIND]",
    "[TARGET_NAME]",
    "[INTERPROCEDURAL_SLICE]",
    "[RECOMMENDATION_TYPE]",
    "[TYPE_NAME]",
    "[TYPE_DEFINITION]",
]

PROMPT_START_MARKERS = (
    "The possible types analyzed from the import information are:",
    "The candidate types analyzed from the import information are:",
)
PROMPT_END_MARKER = "The code you need to make a prediction is:"
DECLARATION_RE = re.compile(
    r"(?mi)^(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?"
    r"(?:class|interface|type|enum)\s+([A-Za-z_$][\w$\.]*)\b"
)
NAME_RE = re.compile(
    r"(?mi)(?:^|\n)\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?"
    r"(?:abstract\s+)?(?:class|interface|type|enum)\s+([A-Za-z_$][\w$\.]*)\b"
)
BUILTIN_TYPE_NAMES = {
    "bool", "bytearray", "bytes", "classmethod", "complex", "dict", "enumerate",
    "filter", "float", "frozenset", "int", "list", "map", "memoryview", "none",
    "nonetype", "object", "property", "range", "reversed", "set", "slice",
    "staticmethod", "str", "super", "tuple", "type", "zip",
}


def iter_records(path: str | Path):
    path = Path(path)
    if path.is_dir():
        for child in sorted(path.rglob("*.jsonl")):
            yield from iter_records(child)
        return
    if path.suffix.lower() == ".jsonl":
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)
        return
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if isinstance(value, list):
        yield from value
        return
    if isinstance(value, dict) and isinstance(value.get("data"), list):
        yield from value["data"]
        return
    raise ValueError(f"Expected a JSON list, JSON object with data[], JSONL, or a JSONL directory: {path}")


def read_records(path: str | Path) -> list[dict[str, Any]]:
    return list(iter_records(path))


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def json_preview(value: Any, max_chars: int = 1600) -> str:
    """Pretty JSON for notebook logs, optionally truncated to a safe length."""
    rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if max_chars > 0 and len(rendered) > max_chars:
        omitted = len(rendered) - max_chars
        return f"{rendered[:max_chars]}\n... <truncated {omitted} characters>"
    return rendered


def print_jsonl_samples(
    path: str | Path,
    sample_count: int = 2,
    max_chars: int = 1600,
    title: str | None = None,
) -> None:
    """Print the first few JSONL rows without loading the whole split into RAM."""
    path = Path(path)
    heading = title or path.name
    if sample_count <= 0:
        return
    if not path.exists():
        print(f"[samples] {heading}: file not found: {path}", flush=True)
        return
    printed = 0
    for row in iter_records(path):
        print(f"\n[samples] {heading} #{printed + 1}\n{json_preview(row, max_chars)}", flush=True)
        printed += 1
        if printed >= sample_count:
            break
    if printed == 0:
        print(f"[samples] {heading}: empty split", flush=True)


def canonical_type_name(value: str) -> str:
    """Loose key used only to align a gold label with a recommendation."""
    value = str(value or "").strip().replace("typing.", "")
    value = re.sub(r"\s+", "", value)
    value = value.split(".")[-1]
    return value.casefold()


def is_builtin_annotation(record: dict[str, Any], label_field: str = "gttype") -> bool:
    category = str(record.get("cat") or "").strip().casefold()
    if category in {"builtin", "builtins"}:
        return True
    original = str(record.get("origttype") or "").strip().casefold()
    if original.startswith("builtins."):
        return True
    # Dataset categories are authoritative; name fallback supports lean custom inputs.
    if category or original:
        return False
    label = str(record.get(label_field) or record.get("processed_gttype") or "").strip()
    base = re.split(r"[\[<|, .]", label.replace("typing.", ""), maxsplit=1)[0].casefold()
    return base in BUILTIN_TYPE_NAMES


def type_name_from_definition(definition: str) -> str:
    match = NAME_RE.search(definition or "")
    if match:
        return match.group(1)
    first = (definition or "").strip().splitlines()[0] if definition.strip() else ""
    if re.fullmatch(r"[A-Za-z_$][\w$\.<>\[\], |?]*", first):
        return first
    return ""


def split_declarations(section: str) -> list[dict[str, str]]:
    section = section.strip()
    if not section:
        return []
    matches = list(DECLARATION_RE.finditer(section))
    if matches:
        result = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
            result.append({"name": match.group(1), "definition": section[match.start():end].strip()})
        return result
    result = []
    for line in section.splitlines():
        line = line.strip(" \t,-")
        if line:
            result.append({"name": type_name_from_definition(line) or line, "definition": line})
    return result


def recommendations_from_prompt(prompt: str) -> list[dict[str, str]]:
    for marker in PROMPT_START_MARKERS:
        start = prompt.find(marker)
        if start >= 0:
            start += len(marker)
            end = prompt.find(PROMPT_END_MARKER, start)
            if end < 0:
                end = len(prompt)
            return split_declarations(prompt[start:end])
    return []


def normalize_recommendations(record: dict[str, Any]) -> list[dict[str, str]]:
    raw = None
    for key in ("recommendation_types", "recommended_types", "type_recommend", "typeRecommended"):
        if record.get(key):
            raw = record[key]
            break

    result: list[dict[str, str]] = []
    if isinstance(raw, str):
        result = split_declarations(raw)
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                result.extend(split_declarations(item))
            elif isinstance(item, dict):
                definition = str(item.get("definition") or item.get("code") or item.get("signature") or "")
                name = str(item.get("name") or type_name_from_definition(definition))
                if name:
                    normalized = {"name": name, "definition": definition or name}
                    for key in ("qualified_name", "package", "module", "source"):
                        if item.get(key):
                            normalized[key] = str(item[key])
                    result.append(normalized)

    if not result:
        prompt = str(record.get("total_prompt") or record.get("totalPrompt") or "")
        result = recommendations_from_prompt(prompt)

    deduped: list[dict[str, str]] = []
    seen = set()
    for item in result:
        key = str(item.get("qualified_name") or canonical_type_name(item["name"])).casefold()
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def get_slice(record: dict[str, Any]) -> str:
    for key in ("interprocedural_slice", "code_slicing", "slicedCode", "slice"):
        if record.get(key):
            return str(record[key]).strip()
    return ""


def get_project(record: dict[str, Any]) -> str:
    if record.get("url"):
        url_parts = [part for part in str(record["url"]).rstrip("/").split("/") if part]
        if len(url_parts) >= 2:
            return "/".join(url_parts[-2:])
        return url_parts[-1] if url_parts else "unknown"
    file_name = str(record.get("file") or record.get("path") or "unknown")
    parts = file_name.replace("\\", "/").split("/")
    if "repos" in parts:
        index = parts.index("repos")
        return "/".join(parts[index + 1:index + 3]) or file_name
    return parts[0] if parts else "unknown"


def deterministic_split(project: str, train_ratio: float, validation_ratio: float) -> str:
    bucket = int(hashlib.sha1(project.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    if bucket < train_ratio:
        return "train"
    if bucket < train_ratio + validation_ratio:
        return "validation"
    return "test"


def format_query(record: dict[str, Any], code_slice: str) -> str:
    language = str(record.get("language") or ("typescript" if str(record.get("file", "")).endswith((".ts", ".tsx")) else "python"))
    return (
        f"[LANGUAGE] {language}\n"
        f"[TARGET_KIND] {record.get('scope', 'unknown')}\n"
        f"[TARGET_NAME] {record.get('name', 'unknown')}\n"
        f"[INTERPROCEDURAL_SLICE]\n{code_slice}"
    )


def format_candidate(name: str, definition: str) -> str:
    return (
        f"[RECOMMENDATION_TYPE]\n[TYPE_NAME] {name}\n"
        f"[TYPE_DEFINITION]\n{definition or name}"
    )


@dataclass
class RetrievalDataset:
    rows: list[dict[str, Any]]

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        return self.rows[index]


class JsonlDataset:
    """Random-access JSONL without loading slices into RAM."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.offsets: list[int] = []
        with self.path.open("rb") as handle:
            while True:
                offset = handle.tell()
                line = handle.readline()
                if not line:
                    break
                if line.strip():
                    self.offsets.append(offset)
        self._handle = None
        self._pid = None

    def __len__(self) -> int:
        return len(self.offsets)

    def __getitem__(self, index: int) -> dict[str, Any]:
        pid = os.getpid()
        if self._handle is None or self._pid != pid:
            if self._handle is not None:
                self._handle.close()
            self._handle = self.path.open("rb")
            self._pid = pid
        self._handle.seek(self.offsets[index])
        return json.loads(self._handle.readline())


class ContrastiveCollator:
    def __init__(self, tokenizer: Any, query_length: int, candidate_length: int, training: bool):
        self.tokenizer = tokenizer
        self.query_length = query_length
        self.candidate_length = candidate_length
        self.training = training

    def __call__(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        candidates = [list(row["candidates"]) for row in rows]
        if self.training:
            for value in candidates:
                random.shuffle(value)
        max_candidates = max(len(value) for value in candidates)
        labels, candidate_mask, flat_candidates = [], [], []
        for value in candidates:
            positive = next(i for i, candidate in enumerate(value) if candidate["is_positive"])
            labels.append(positive)
            candidate_mask.append([True] * len(value) + [False] * (max_candidates - len(value)))
            padded = value + [{"text": "", "is_positive": False}] * (max_candidates - len(value))
            flat_candidates.extend(candidate["text"] for candidate in padded)

        query_tokens = self.tokenizer(
            [row["query"] for row in rows], padding=True, truncation=True,
            max_length=self.query_length, return_tensors="pt",
        )
        candidate_tokens = self.tokenizer(
            flat_candidates, padding=True, truncation=True,
            max_length=self.candidate_length, return_tensors="pt",
        )
        import torch

        return {
            "query_input_ids": query_tokens["input_ids"],
            "query_attention_mask": query_tokens["attention_mask"],
            "candidate_input_ids": candidate_tokens["input_ids"],
            "candidate_attention_mask": candidate_tokens["attention_mask"],
            "candidate_mask": torch.tensor(candidate_mask, dtype=torch.bool),
            "labels": torch.tensor(labels, dtype=torch.long),
            "candidate_names": [[candidate["name"] for candidate in value] for value in candidates],
            "gold": [row["label"] for row in rows],
        }
