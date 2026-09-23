"""Generate the local SSH GPU notebook for Qwen2.5-Coder fine-tuning."""
from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent


def markdown(source: str) -> dict:
    return {
        "cell_type": "markdown",
        "id": "",
        "metadata": {},
        "source": (dedent(source).strip() + "\n").splitlines(keepends=True),
    }


def code(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "id": "",
        "metadata": {},
        "outputs": [],
        "source": (dedent(source).strip() + "\n").splitlines(keepends=True),
    }


def build_notebook() -> dict:
    cells = [
        markdown("""
        # TypePro: train và infer Qwen2.5-Coder-0.5B trên GPU SSH

        Notebook dùng Dataset TypePro đã tải từ Kaggle, kiểm tra dữ liệu, train
        toàn bộ tập train bằng QLoRA 4-bit trên một RTX A4000 và infer toàn bộ
        tập test. Chạy các cell theo thứ tự. Không cần đặt Kaggle token trong
        notebook.
        """),
        markdown("## 1. Cấu hình"),
        code(f"""
        from pathlib import Path

        REPO_DIR = Path({str(REPO_ROOT)!r})
        DATA_DIR = REPO_DIR / "datasets" / "typepro-python-generative-v15"
        PIPELINE_DIR = REPO_DIR / "codet5p_type_retrieval"
        VENV_DIR = REPO_DIR / ".venv"
        OUTPUT_DIR = REPO_DIR / "outputs" / "qwen25-coder-05b-8192"
        PREDICTIONS = OUTPUT_DIR / "test_predictions.jsonl"

        MODEL_NAME = "Qwen/Qwen2.5-Coder-0.5B-Instruct"
        INPUT_LENGTH = 8192
        LABEL_LENGTH = 64
        EPOCHS = 3
        TRAIN_BATCH_SIZE = 1
        GRADIENT_ACCUMULATION_STEPS = 16
        TRAIN_SAMPLES = None  # None = toàn bộ tập train
        INFERENCE_BATCH_SIZE = 1

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        """),
        markdown("## 2. Kiểm tra máy, GPU và môi trường"),
        code("""
        import json
        import os
        import selectors
        import signal
        import shutil
        import subprocess
        import time

        def run(command, cwd=REPO_DIR, env=None):
            command = [str(value) for value in command]
            print("+", " ".join(command), flush=True)
            child_env = os.environ.copy()
            if env is not None:
                child_env.update(env)
            # A child process that inherits Jupyter's OS-level stdout can write
            # to the server log instead of the cell.  Pipe both streams back
            # through Python so progress is visible in the notebook itself.
            child_env["PYTHONUNBUFFERED"] = "1"
            started_at = time.monotonic()
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=child_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                start_new_session=True,
            )
            assert process.stdout is not None
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            try:
                while True:
                    if not selector.select(timeout=30):
                        elapsed = int(time.monotonic() - started_at)
                        print(f"[đang chạy: {elapsed}s, chưa có log mới]", flush=True)
                        continue
                    chunk = process.stdout.read(4096)
                    if not chunk:
                        break
                    print(chunk.decode("utf-8", errors="replace"), end="", flush=True)
                return_code = process.wait()
            except BaseException:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise
            finally:
                selector.close()
            if return_code:
                raise subprocess.CalledProcessError(return_code, command)

        PYTHON = VENV_DIR / "bin" / "python"
        ACCELERATE = VENV_DIR / "bin" / "accelerate"
        if not PYTHON.is_file() or not ACCELERATE.is_file():
            raise RuntimeError(f"Môi trường chưa sẵn sàng: {VENV_DIR}")
        if shutil.which("nvidia-smi") is None:
            raise RuntimeError("Không tìm thấy nvidia-smi")

        run(["nvidia-smi", "--query-gpu=index,name,memory.total,memory.free,driver_version", "--format=csv"])
        run(["df", "-h", REPO_DIR])
        run([PYTHON, "-c", "import torch; assert torch.cuda.is_available(); "
             "assert torch.cuda.device_count() == 1; "
             "print({'torch': torch.__version__, 'cuda': torch.version.cuda, "
             "'gpu': torch.cuda.get_device_name(0)})"])

        os.environ["CUDA_VISIBLE_DEVICES"] = "0"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        os.environ["HF_HOME"] = str(Path.home() / ".cache" / "huggingface")
        """),
        markdown("## 3. Xác minh Dataset Kaggle đã tải"),
        code("""
        required = ["manifest.json", "train.jsonl", "validation.jsonl", "test.jsonl"]
        missing = [name for name in required if not (DATA_DIR / name).is_file()]
        if missing:
            raise RuntimeError(f"Dataset chưa tải đủ, thiếu: {missing}")
        run([PYTHON, PIPELINE_DIR / "verify_dataset.py", "--data-dir", DATA_DIR])

        manifest = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
        print(json.dumps({
            "dataset": str(DATA_DIR),
            "schema_version": manifest.get("schema_version"),
            "prepared_counts": manifest.get("split", {}).get("prepared_counts"),
            "prepared_projects": manifest.get("split", {}).get("prepared_projects"),
        }, indent=2, ensure_ascii=False))
        """),
        markdown("""
        ## 4. Fine-tune toàn bộ tập train

        Cấu hình đã được smoke test ở chuỗi 8192 token trên RTX A4000 16 GB.
        Cell này chạy lâu. Checkpoint tốt nhất được lưu trong `OUTPUT_DIR/best`.
        """),
        code("""
        train_command = [
            ACCELERATE, "launch",
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
            "--preview-samples", "0",
            "--seed", "13",
            "--log-every", "50",
        ]
        if TRAIN_SAMPLES is not None:
            train_command.extend(["--train-samples", TRAIN_SAMPLES])

        train_env = os.environ.copy()
        train_env["CUDA_VISIBLE_DEVICES"] = "0"
        run(train_command, env=train_env)
        """),
        markdown("## 5. Infer toàn bộ tập test và tính exact match"),
        code("""
        best_checkpoint = OUTPUT_DIR / "best"
        if not best_checkpoint.is_dir():
            raise RuntimeError(f"Không tìm thấy checkpoint: {best_checkpoint}")

        run([
            PYTHON, "-u", PIPELINE_DIR / "infer_generative.py",
            "--checkpoint", best_checkpoint,
            "--model-name", MODEL_NAME,
            "--input", DATA_DIR / "test.jsonl",
            "--output", PREDICTIONS,
            "--input-length", INPUT_LENGTH,
            "--label-length", LABEL_LENGTH,
            "--batch-size", INFERENCE_BATCH_SIZE,
        ], env=os.environ.copy())
        print("Predictions:", PREDICTIONS)
        """),
        markdown("## 6. Đóng gói adapter và kết quả inference"),
        code("""
        import tarfile

        archive = OUTPUT_DIR / "typepro_qwen25_05b_8192_result.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(OUTPUT_DIR / "best", arcname="best")
            bundle.add(PREDICTIONS, arcname=PREDICTIONS.name)
        print("Kết quả đã đóng gói:", archive)
        """),
    ]
    for index, cell in enumerate(cells):
        cell["id"] = f"cell-{index:03d}"
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": ".venv (3.12.11)",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.12.11"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> None:
    output = ROOT / "01_typepro_qwen25_05b_a4000.ipynb"
    output.write_text(
        json.dumps(build_notebook(), ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
