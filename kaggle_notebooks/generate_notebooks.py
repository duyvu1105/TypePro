"""Generate upload-ready Kaggle notebooks for TypePro sharding and training.

The generated notebooks never contain a literal Kaggle credential. They read
KAGGLE_USERNAME and KAGGLE_KEY from Kaggle Secrets at runtime.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from textwrap import dedent
from uuid import uuid4


ROOT = Path(__file__).resolve().parent


def markdown(source: str) -> dict:
    return {
        "cell_type": "markdown",
        "id": uuid4().hex[:8],
        "metadata": {},
        "source": dedent(source).strip() + "\n",
    }


def code(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "id": uuid4().hex[:8],
        "metadata": {},
        "outputs": [],
        "source": dedent(source).strip() + "\n",
    }


def notebook(cells: list[dict], gpu: bool = False) -> dict:
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12"},
            "kaggle": {
                "accelerator": "nvidiaTeslaT4" if gpu else "none",
                "isGpuEnabled": gpu,
                "isInternetEnabled": True,
                "language": "python",
                "sourceType": "notebook",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def shard_notebook(index: int, count: int, repository: str, branch: str) -> dict:
    title = f"TypePro Python dataset shard {index:02d}/{count - 1:02d}"
    return notebook([
        markdown(f"""
        # {title}

        Settings required: **Internet ON**, accelerator **None/CPU**. Add account
        secrets `KAGGLE_USERNAME` and `KAGGLE_KEY`. This notebook processes shard
        `{index}` of `{count}` and publishes a private dataset named
        `typepro-build-shard-{index:02d}`.
        """),
        code(f"""
        SHARD_INDEX = {index}
        SHARD_COUNT = {count}
        REPOSITORY = {repository!r}
        BRANCH = {branch!r}
        SEED = 13
        TEST_PROJECTS = 100
        VALIDATION_PROJECT_RATIO = 0.10
        SLICE_LOG_EVERY = 50

        from pathlib import Path

        REPO_DIR = Path("/kaggle/working/TypePro")
        WORK_DIR = Path(f"/kaggle/working/typepro_build_shard_{{SHARD_INDEX:02d}}")
        PUBLISH_DIR = Path(f"/kaggle/working/publish_shard_{{SHARD_INDEX:02d}}")
        print({{
            "shard_index": SHARD_INDEX,
            "shard_count": SHARD_COUNT,
            "work_dir": str(WORK_DIR),
        }})
        """),
        markdown("""
        ## Authenticate safely

        Values are read from Kaggle Secrets and are never printed.
        """),
        code("""
        import os
        from kaggle_secrets import UserSecretsClient

        secrets = UserSecretsClient()
        os.environ["KAGGLE_USERNAME"] = secrets.get_secret("KAGGLE_USERNAME")
        os.environ["KAGGLE_KEY"] = secrets.get_secret("KAGGLE_KEY")
        os.environ["PYTHONUNBUFFERED"] = "1"
        print("Kaggle credentials loaded for:", os.environ["KAGGLE_USERNAME"])
        """),
        markdown("## Clone TypePro and install builder dependencies"),
        code("""
        import shutil
        import subprocess
        import sys

        def run(command, cwd=None):
            print("+", " ".join(map(str, command)), flush=True)
            subprocess.run([str(value) for value in command], cwd=cwd, check=True)

        if not REPO_DIR.exists():
            run(["git", "clone", "--branch", BRANCH, "--single-branch", REPOSITORY, REPO_DIR])
        else:
            print("Using existing repository:", REPO_DIR)

        PIPELINE_DIR = REPO_DIR / "codet5p_type_retrieval"
        run([sys.executable, "-m", "pip", "install", "-q", "-r", PIPELINE_DIR / "requirements-build.txt"])
        """),
        markdown("""
        ## Optional automatic resume

        If the private shard dataset already exists, its archive is downloaded
        and restored before slicing. A missing dataset simply means this is the
        first run.
        """),
        code("""
        import zipfile

        dataset_id = f"{os.environ['KAGGLE_USERNAME']}/typepro-build-shard-{SHARD_INDEX:02d}"
        resume_dir = Path(f"/kaggle/working/resume_shard_{SHARD_INDEX:02d}")
        resume_dir.mkdir(parents=True, exist_ok=True)
        probe = subprocess.run(
            ["kaggle", "datasets", "files", dataset_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if probe.returncode == 0 and not WORK_DIR.exists():
            run(["kaggle", "datasets", "download", "-d", dataset_id, "-p", resume_dir, "--unzip"])
            archives = list(resume_dir.glob("typepro_build_shard_*.zip"))
            if len(archives) != 1:
                raise RuntimeError(f"Expected one shard archive, found: {archives}")
            with zipfile.ZipFile(archives[0]) as bundle:
                bundle.extractall("/kaggle/working")
            print("Restored previous shard state:", WORK_DIR)
        else:
            print("Starting new shard or using current working state")
        """),
        markdown("## Download metadata and create the deterministic project split"),
        code("""
        prepare = PIPELINE_DIR / "prepare_dataset.py"
        common = [
            "--typepro-root", REPO_DIR,
            "--work-dir", WORK_DIR,
            "--split-profile", "paper_project",
            "--test-projects", TEST_PROJECTS,
            "--validation-project-ratio", VALIDATION_PROJECT_RATIO,
            "--seed", SEED,
            "--preview-samples", 1,
            "--preview-max-chars", 1200,
        ]
        run([sys.executable, "-u", prepare, "--stage", "metadata", *common])
        """),
        markdown("## Clone repositories and build interprocedural slices"),
        code("""
        run([
            sys.executable, "-u", prepare,
            "--stage", "slice",
            *common,
            "--shard-count", SHARD_COUNT,
            "--shard-index", SHARD_INDEX,
            "--slice-log-every", SLICE_LOG_EVERY,
            "--build-import-kb",
            "--download-missing-imports",
            "--kb-max-files-per-package", 3000,
        ])
        """),
        markdown("## Verify that this shard attempted every assigned project"),
        code("""
        import json
        sys.path.insert(0, str(PIPELINE_DIR))
        from prepare_dataset import project_from_row, read_json, stable_number

        projects = set()
        for split in ("train", "validation", "test"):
            for row in read_json(WORK_DIR / "metadata" / f"{split}.json"):
                projects.add(project_from_row(row))
        selected = {
            project for project in projects
            if stable_number(project, SEED + 4) % SHARD_COUNT == SHARD_INDEX
        }
        statuses = []
        for path in (WORK_DIR / "project_status").glob("*.json"):
            statuses.append(json.loads(path.read_text(encoding="utf-8")))
        attempted = {item.get("project") for item in statuses}
        missing = sorted(selected - attempted)
        summary = {
            "shard_index": SHARD_INDEX,
            "shard_count": SHARD_COUNT,
            "selected_projects": len(selected),
            "attempted_projects": len(selected & attempted),
            "successful_projects": sum(item.get("project") in selected and "error" not in item for item in statuses),
            "failed_projects": sum(item.get("project") in selected and "error" in item for item in statuses),
            "exported_slices": sum(int(item.get("exported", 0)) for item in statuses if item.get("project") in selected),
            "missing_projects": missing,
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        (WORK_DIR / "shard_manifest.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        if missing:
            raise RuntimeError(f"Shard is incomplete: {len(missing)} projects missing")
        """),
        markdown("## Package and publish this shard as a private Kaggle Dataset"),
        code("""
        PUBLISH_DIR.mkdir(parents=True, exist_ok=True)
        archive_base = PUBLISH_DIR / f"typepro_build_shard_{SHARD_INDEX:02d}"
        archive = Path(shutil.make_archive(str(archive_base), "zip", WORK_DIR.parent, WORK_DIR.name))
        metadata = {
            "title": f"TypePro Python build shard {SHARD_INDEX:02d}",
            "id": dataset_id,
            "licenses": [{"name": "CC-BY-4.0"}],
        }
        (PUBLISH_DIR / "dataset-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        exists = subprocess.run(
            ["kaggle", "datasets", "files", dataset_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
        if exists:
            run(["kaggle", "datasets", "version", "-p", PUBLISH_DIR, "--dir-mode", "zip", "-m", "Update completed TypePro shard"])
        else:
            run(["kaggle", "datasets", "create", "-p", PUBLISH_DIR, "--dir-mode", "zip"])
        print("Published:", dataset_id)
        print("Archive bytes:", archive.stat().st_size)
        """),
    ])


def merge_notebook(count: int, repository: str, branch: str) -> dict:
    return notebook([
        markdown(f"""
        # Merge {count} TypePro shards and publish the final dataset

        Settings: **Internet ON**, accelerator **None/CPU**. Add secrets
        `KAGGLE_USERNAME` and `KAGGLE_KEY`. Run only after all `{count}` private
        shard datasets have been published successfully.
        """),
        code(f"""
        SHARD_COUNT = {count}
        REPOSITORY = {repository!r}
        BRANCH = {branch!r}
        FINAL_DATASET_SLUG = "typepro-python-contrastive"
        SEED = 13

        import json
        import os
        import shutil
        import subprocess
        import sys
        import zipfile
        from pathlib import Path
        from kaggle_secrets import UserSecretsClient

        secrets = UserSecretsClient()
        os.environ["KAGGLE_USERNAME"] = secrets.get_secret("KAGGLE_USERNAME")
        os.environ["KAGGLE_KEY"] = secrets.get_secret("KAGGLE_KEY")
        os.environ["PYTHONUNBUFFERED"] = "1"

        REPO_DIR = Path("/kaggle/working/TypePro")
        DOWNLOAD_DIR = Path("/kaggle/working/downloaded_shards")
        MERGED_BUILD = Path("/kaggle/working/typepro_build")
        FINAL_DIR = Path("/kaggle/working/typepro_python_contrastive")

        def run(command, cwd=None):
            print("+", " ".join(map(str, command)), flush=True)
            subprocess.run([str(value) for value in command], cwd=cwd, check=True)
        """),
        markdown("## Clone code and install dependencies"),
        code("""
        if not REPO_DIR.exists():
            run(["git", "clone", "--branch", BRANCH, "--single-branch", REPOSITORY, REPO_DIR])
        PIPELINE_DIR = REPO_DIR / "codet5p_type_retrieval"
        run([sys.executable, "-m", "pip", "install", "-q", "-r", PIPELINE_DIR / "requirements-build.txt"])
        """),
        markdown("## Download and extract every private shard dataset"),
        code("""
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        shard_builds = []
        for index in range(SHARD_COUNT):
            dataset_id = f"{os.environ['KAGGLE_USERNAME']}/typepro-build-shard-{index:02d}"
            target = DOWNLOAD_DIR / f"shard_{index:02d}"
            target.mkdir(parents=True, exist_ok=True)
            run(["kaggle", "datasets", "download", "-d", dataset_id, "-p", target, "--unzip"])
            archives = list(target.glob("typepro_build_shard_*.zip"))
            if len(archives) != 1:
                raise RuntimeError(f"{dataset_id}: expected one build archive, found {archives}")
            with zipfile.ZipFile(archives[0]) as bundle:
                bundle.extractall(target)
            builds = list(target.glob("typepro_build_shard_*"))
            if len(builds) != 1:
                raise RuntimeError(f"{dataset_id}: cannot locate extracted build directory")
            marker = json.loads((builds[0] / "shard_manifest.json").read_text(encoding="utf-8"))
            if marker["shard_index"] != index or marker["shard_count"] != SHARD_COUNT or marker["missing_projects"]:
                raise RuntimeError(f"Invalid/incomplete shard marker: {marker}")
            shard_builds.append(builds[0])
            print(f"Validated shard {index:02d}: {marker['attempted_projects']} projects")
        print("All shard build directories:", [str(path) for path in shard_builds])
        """),
        markdown("## Merge shard outputs"),
        code("""
        merge_script = PIPELINE_DIR / "merge_shards.py"
        run([
            sys.executable, "-u", merge_script,
            "--shard-build-dirs", *shard_builds,
            "--work-dir", MERGED_BUILD,
        ])
        """),
        markdown("## Finalize contrastive train/validation/test"),
        code("""
        prepare = PIPELINE_DIR / "prepare_dataset.py"
        run([
            sys.executable, "-u", prepare,
            "--stage", "finalize",
            "--typepro-root", REPO_DIR,
            "--work-dir", MERGED_BUILD,
            "--output-dir", FINAL_DIR,
            "--split-profile", "paper_project",
            "--test-projects", 100,
            "--validation-project-ratio", 0.10,
            "--max-negatives", 7,
            "--seed", SEED,
            "--preview-samples", 2,
            "--preview-max-chars", 1600,
            "--log-every", 10000,
        ])
        run([sys.executable, PIPELINE_DIR / "verify_dataset.py", "--data-dir", FINAL_DIR])
        """),
        markdown("## Display exact counts and examples"),
        code("""
        manifest = json.loads((FINAL_DIR / "manifest.json").read_text(encoding="utf-8"))
        stats = json.loads((FINAL_DIR / "preprocess_stats.json").read_text(encoding="utf-8"))
        print(json.dumps({
            "output": manifest["output"],
            "prepared_counts": manifest["split"]["prepared_counts"],
            "prepared_projects": manifest["split"]["prepared_projects"],
            "preprocess_stats": stats,
        }, indent=2, ensure_ascii=False))
        for split in ("train", "validation", "test"):
            print(f"\\n===== {split.upper()} SAMPLES =====")
            with (FINAL_DIR / f"{split}.jsonl").open(encoding="utf-8") as handle:
                for _, line in zip(range(2), handle):
                    print(json.dumps(json.loads(line), indent=2, ensure_ascii=False)[:3000])
        """),
        markdown("## Publish final private Kaggle Dataset"),
        code("""
        final_id = f"{os.environ['KAGGLE_USERNAME']}/{FINAL_DATASET_SLUG}"
        run([
            sys.executable, PIPELINE_DIR / "publish_kaggle.py",
            "--data-dir", FINAL_DIR,
            "--dataset-id", final_id,
            "--title", "TypePro Python Parameter Third-Party Contrastive Dataset",
            "--message", f"Merge {SHARD_COUNT} verified TypePro shards",
        ])
        completion = {
            "dataset_id": final_id,
            "shard_count": SHARD_COUNT,
            "output": manifest["output"],
        }
        (FINAL_DIR / "MERGE_COMPLETE.json").write_text(
            json.dumps(completion, indent=2), encoding="utf-8"
        )
        print(json.dumps(completion, indent=2))
        """),
    ])


def train_notebook(repository: str, branch: str) -> dict:
    return notebook([
        markdown("""
        # Fine-tune CodeT5+ and infer on the TypePro test split

        Settings: **Internet ON**, accelerator **GPU**. Attach the final private
        dataset `typepro-python-contrastive` using **Add Input**.
        """),
        code(f"""
        REPOSITORY = {repository!r}
        BRANCH = {branch!r}
        MODEL_NAME = "Salesforce/codet5p-220m-py"
        QUERY_LENGTH = 768
        CANDIDATE_LENGTH = 256
        EPOCHS = 3

        import json
        import subprocess
        import sys
        from pathlib import Path

        REPO_DIR = Path("/kaggle/working/TypePro")
        OUTPUT_DIR = Path("/kaggle/working/codet5p-typepro-python")

        def run(command, cwd=None):
            print("+", " ".join(map(str, command)), flush=True)
            subprocess.run([str(value) for value in command], cwd=cwd, check=True)

        if not REPO_DIR.exists():
            run(["git", "clone", "--branch", BRANCH, "--single-branch", REPOSITORY, REPO_DIR])
        PIPELINE_DIR = REPO_DIR / "codet5p_type_retrieval"
        run([sys.executable, "-m", "pip", "install", "-q", "-r", PIPELINE_DIR / "requirements.txt"])
        """),
        markdown("## Locate and verify the attached processed dataset"),
        code("""
        candidates = []
        for path in Path("/kaggle/input").rglob("manifest.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if value.get("schema_version", "").startswith("typepro-codet5p-contrastive"):
                candidates.append(path.parent)
        if len(candidates) != 1:
            raise RuntimeError(f"Expected exactly one TypePro processed dataset, found {candidates}")
        DATA_DIR = candidates[0]
        print("Using dataset:", DATA_DIR)
        run([sys.executable, PIPELINE_DIR / "verify_dataset.py", "--data-dir", DATA_DIR])
        """),
        markdown("## Contrastive fine-tuning"),
        code("""
        run([
            sys.executable, "-u", PIPELINE_DIR / "train.py",
            "--data-dir", DATA_DIR,
            "--output-dir", OUTPUT_DIR,
            "--model-name", MODEL_NAME,
            "--projection-dim", 256,
            "--query-length", QUERY_LENGTH,
            "--candidate-length", CANDIDATE_LENGTH,
            "--batch-size", 2,
            "--gradient-accumulation-steps", 8,
            "--epochs", EPOCHS,
            "--learning-rate", "2e-5",
            "--mixed-precision", "fp16",
            "--gradient-checkpointing",
            "--preview-samples", 2,
            "--preview-max-chars", 1600,
            "--seed", 13,
        ])
        """),
        markdown("## Batched inference and test metrics"),
        code("""
        predictions = Path("/kaggle/working/test_predictions.jsonl")
        run([
            sys.executable, "-u", PIPELINE_DIR / "infer.py",
            "--checkpoint", OUTPUT_DIR / "best",
            "--input", DATA_DIR / "test.jsonl",
            "--output", predictions,
            "--query-length", QUERY_LENGTH,
            "--candidate-length", CANDIDATE_LENGTH,
            "--batch-size", 4,
            "--top-k", 5,
            "--preview-samples", 3,
            "--log-every", 1000,
        ])
        print("Predictions:", predictions)
        """),
    ], gpu=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shards", type=int, default=5)
    parser.add_argument("--repository", default="https://github.com/duyvu1105/TypePro.git")
    parser.add_argument("--branch", default="main")
    args = parser.parse_args()
    if args.shards <= 0:
        raise ValueError("shards must be positive")

    ROOT.mkdir(parents=True, exist_ok=True)
    for pattern in ("[0-9][0-9]_typepro_shard_*.ipynb", "[0-9][0-9]_merge_finalize.ipynb", "[0-9][0-9]_train_and_infer.ipynb"):
        for stale in ROOT.glob(pattern):
            stale.unlink()
    generated = []
    for index in range(args.shards):
        path = ROOT / f"{index + 1:02d}_typepro_shard_{index:02d}.ipynb"
        path.write_text(
            json.dumps(shard_notebook(index, args.shards, args.repository, args.branch), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        generated.append(path.name)
    merge_path = ROOT / f"{args.shards + 1:02d}_merge_finalize.ipynb"
    merge_path.write_text(
        json.dumps(merge_notebook(args.shards, args.repository, args.branch), ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    generated.append(merge_path.name)
    train_path = ROOT / f"{args.shards + 2:02d}_train_and_infer.ipynb"
    train_path.write_text(
        json.dumps(train_notebook(args.repository, args.branch), ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    generated.append(train_path.name)
    print(json.dumps({"generated": generated}, indent=2))


if __name__ == "__main__":
    main()
