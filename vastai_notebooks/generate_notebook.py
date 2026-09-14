"""Generate the single-GPU Vast.ai training notebook.

Keep executable notebook changes in this generator so the checked-in ipynb is
reproducible.  No credentials are embedded in either artifact.
"""
from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent


ROOT = Path(__file__).resolve().parent


def markdown(source: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": dedent(source).strip() + "\n",
    }


def code(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": dedent(source).strip() + "\n",
    }


def build_notebook() -> dict:
    cells = [
        markdown("""
        # TypePro: fine-tune Qwen2.5-Coder trên một GPU Vast.ai

        Notebook này tải Dataset TypePro private từ Kaggle (hoặc dùng bản đã
        upload vào `/workspace/datasets`), kiểm tra dữ liệu, fine-tune bằng
        QLoRA 4-bit trên **đúng một GPU**, rồi chạy đánh giá trên tập test.

        Khuyến nghị cho lần đầu: GPU có ít nhất 24 GB VRAM, 100 GB disk, image
        PyTorch/CUDA có Jupyter + SSH. Không nhập token trực tiếp vào mã nguồn.
        """),
        markdown("## 1. Cấu hình lần chạy"),
        code("""
        REPOSITORY = "https://github.com/duyvu1105/TypePro.git"
        REVISION = "main"  # Nên thay bằng Git commit SHA để tái lập thí nghiệm.
        KAGGLE_DATASET = "duyvu1105/typepro-python-generative"

        MODEL_NAME = "Qwen/Qwen2.5-Coder-0.5B-Instruct"
        INPUT_LENGTH = 8192
        LABEL_LENGTH = 128
        EPOCHS = 3
        TRAIN_BATCH_SIZE = 1
        GRADIENT_ACCUMULATION_STEPS = 16
        TRAIN_SAMPLES = None  # Đặt None để dùng toàn bộ tập train.
        INFERENCE_BATCH_SIZE = 2

        from pathlib import Path

        WORKSPACE = Path("/workspace")
        REPO_DIR = WORKSPACE / "TypePro"
        DATA_ROOT = WORKSPACE / "datasets" / "typepro-python-generative"
        OUTPUT_DIR = WORKSPACE / "outputs" / "qwen25-typepro"
        PREDICTIONS = WORKSPACE / "outputs" / "test_predictions.jsonl"

        for directory in (DATA_ROOT, OUTPUT_DIR, PREDICTIONS.parent):
            directory.mkdir(parents=True, exist_ok=True)
        """),
        markdown("## 2. Kiểm tra máy và đúng một GPU"),
        code("""
        import os
        import shutil
        import subprocess
        import sys

        def run(command, cwd=None, env=None):
            command = [str(value) for value in command]
            print("+", " ".join(command), flush=True)
            subprocess.run(command, cwd=cwd, env=env, check=True)

        if shutil.which("nvidia-smi") is None:
            raise RuntimeError("Không tìm thấy nvidia-smi; hãy chọn instance có GPU NVIDIA.")
        run(["nvidia-smi", "--query-gpu=index,name,memory.total,driver_version", "--format=csv"])
        run(["df", "-h", "/workspace"])

        # Khóa pipeline vào GPU đầu tiên ngay cả khi offer vô tình có nhiều GPU.
        os.environ["CUDA_VISIBLE_DEVICES"] = "0"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        os.environ["HF_HOME"] = str(WORKSPACE / ".cache" / "huggingface")
        os.environ["PIP_CACHE_DIR"] = str(WORKSPACE / ".cache" / "pip")
        """),
        markdown("## 3. Lấy mã nguồn và cài dependency"),
        code("""
        if not REPO_DIR.exists():
            run(["git", "clone", REPOSITORY, REPO_DIR])
        else:
            print("Dùng lại repository đã có:", REPO_DIR)

        # Fetch + checkout giúp REVISION có thể là branch, tag hoặc commit SHA.
        run(["git", "fetch", "origin"], cwd=REPO_DIR)
        run(["git", "checkout", REVISION], cwd=REPO_DIR)
        if REVISION == "main":
            run(["git", "pull", "--ff-only", "origin", "main"], cwd=REPO_DIR)

        PIPELINE_DIR = REPO_DIR / "codet5p_type_retrieval"
        run([
            sys.executable, "-m", "pip", "install", "-q",
            "-r", PIPELINE_DIR / "requirements.txt",
        ])
        """),
        markdown("""
        ## 4. Chuẩn bị Dataset

        Nếu `DATA_ROOT` chưa có Dataset hợp lệ, cell sẽ hỏi Kaggle API token bằng
        ô nhập ẩn rồi tải Dataset private. Có thể bỏ qua token bằng cách upload/
        giải nén Dataset vào `/workspace/datasets/typepro-python-generative`
        trước khi chạy cell này.
        """),
        code("""
        import getpass
        import json

        EXPECTED_SCHEMA = "typepro-codet5p-generative-project-kb-v2"

        def find_data_dirs(root):
            matches = []
            for manifest_path in root.rglob("manifest.json"):
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if manifest.get("schema_version") == EXPECTED_SCHEMA:
                    matches.append(manifest_path.parent)
            return matches

        candidates = find_data_dirs(DATA_ROOT)
        if not candidates:
            run([sys.executable, "-m", "pip", "install", "-q", "kaggle==1.7.4.2"])
            token = os.environ.get("KAGGLE_API_TOKEN") or getpass.getpass(
                "Kaggle API token (input is hidden): "
            )
            if not token.strip():
                raise RuntimeError("Không có token và không tìm thấy Dataset local.")
            download_env = os.environ.copy()
            download_env["KAGGLE_API_TOKEN"] = token.strip()
            run([
                "kaggle", "datasets", "download",
                "--dataset", KAGGLE_DATASET,
                "--path", DATA_ROOT,
                "--unzip",
            ], env=download_env)
            del token, download_env
            candidates = find_data_dirs(DATA_ROOT)

        if len(candidates) != 1:
            raise RuntimeError(f"Cần đúng một Dataset TypePro, tìm thấy: {candidates}")
        DATA_DIR = candidates[0]
        print("Dataset:", DATA_DIR)
        run([sys.executable, PIPELINE_DIR / "verify_dataset.py", "--data-dir", DATA_DIR])
        """),
        markdown("## 5. Xác nhận PyTorch nhìn thấy đúng một GPU"),
        code("""
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("PyTorch không nhìn thấy CUDA. Hãy đổi sang image PyTorch/CUDA.")
        if torch.cuda.device_count() != 1:
            raise RuntimeError(f"Pipeline yêu cầu đúng 1 GPU visible, thấy {torch.cuda.device_count()}.")
        properties = torch.cuda.get_device_properties(0)
        print({
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "gpu": properties.name,
            "vram_gb": round(properties.total_memory / 1024**3, 1),
        })
        """),
        markdown("""
        ## 6. Fine-tune QLoRA trên một GPU

        Cell này có thể chạy lâu. Checkpoint tốt nhất được lưu ở
        `/workspace/outputs/qwen25-typepro/best`. Nếu bị thiếu VRAM, giảm
        `INPUT_LENGTH` xuống 4096; không tăng batch trước khi chạy ổn định.
        """),
        code("""
        train_command = [
            "accelerate", "launch",
            "--num_machines", "1",
            "--num_processes", "1",
            "--mixed_precision", "fp16",
            PIPELINE_DIR / "train_generative.py",
            "--data-dir", DATA_DIR,
            "--output-dir", OUTPUT_DIR,
            "--model-name", MODEL_NAME,
            "--input-length", INPUT_LENGTH,
            "--label-length", LABEL_LENGTH,
            "--batch-size", TRAIN_BATCH_SIZE,
            "--gradient-accumulation-steps", GRADIENT_ACCUMULATION_STEPS,
            "--epochs", EPOCHS,
            "--learning-rate", "2e-5",
            "--mixed-precision", "fp16",
            "--attn-implementation", "sdpa",
            "--gradient-checkpointing",
            "--group-by-length",
            "--seed", 13,
        ]
        if TRAIN_SAMPLES is not None:
            train_command.extend(["--train-samples", TRAIN_SAMPLES])
        run(train_command, cwd=REPO_DIR)
        """),
        markdown("## 7. Chạy inference và tính exact-match trên tập test"),
        code("""
        best_checkpoint = OUTPUT_DIR / "best"
        if not best_checkpoint.is_dir():
            raise RuntimeError(f"Không tìm thấy checkpoint: {best_checkpoint}")
        run([
            sys.executable, "-u", PIPELINE_DIR / "infer_generative.py",
            "--checkpoint", best_checkpoint,
            "--model-name", MODEL_NAME,
            "--input", DATA_DIR / "test.jsonl",
            "--output", PREDICTIONS,
            "--input-length", INPUT_LENGTH,
            "--label-length", LABEL_LENGTH,
            "--batch-size", INFERENCE_BATCH_SIZE,
        ], cwd=REPO_DIR)
        print("Predictions:", PREDICTIONS)
        """),
        markdown("## 8. Đóng gói kết quả trước khi dừng/xóa instance"),
        code("""
        import shutil

        bundle_root = WORKSPACE / "outputs" / "typepro_vastai_result"
        if bundle_root.exists():
            shutil.rmtree(bundle_root)
        bundle_root.mkdir(parents=True)
        shutil.copytree(OUTPUT_DIR / "best", bundle_root / "best")
        shutil.copy2(PREDICTIONS, bundle_root / PREDICTIONS.name)
        archive = shutil.make_archive(
            str(WORKSPACE / "outputs" / "typepro_vastai_result"),
            "gztar",
            root_dir=bundle_root,
        )
        print("Hãy tải file này về trước khi xóa instance:", archive)
        """),
    ]
    for index, cell in enumerate(cells):
        cell["id"] = f"cell-{index:03d}"
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> None:
    output = ROOT / "01_typepro_qwen25_1gpu.ipynb"
    output.write_text(
        json.dumps(build_notebook(), ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
