#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="${TYPEPRO_REPO_DIR:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)}"
DATA_DIR="${TYPEPRO_DATA_DIR:-$REPO_DIR/datasets/typepro-python-generative-v19}"
PIPELINE_DIR="$REPO_DIR/typepro"
VENV_DIR="${TYPEPRO_VENV_DIR:-$REPO_DIR/.venv}"
OUTPUT_DIR="${TYPEPRO_OUTPUT_DIR:-$REPO_DIR/outputs/qwen25-coder-05b}"
LOG_FILE="$OUTPUT_DIR/train_tmux.log"

mkdir -p "$OUTPUT_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

echo
echo "===== TypePro training + inference started: $(date --iso-8601=seconds) ====="
echo "Log: $LOG_FILE"

finish() {
  exit_code=$?
  echo "===== TypePro training + inference finished: $(date --iso-8601=seconds), exit=$exit_code ====="
}
trap finish EXIT

export CUDA_VISIBLE_DEVICES=0
export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"

cd "$REPO_DIR"
"$VENV_DIR/bin/accelerate" launch \
  --num_machines 1 \
  --num_processes 1 \
  --mixed_precision fp16 \
  "$PIPELINE_DIR/training/generative.py" \
  --data-dir "$DATA_DIR" \
  --output-dir "$OUTPUT_DIR" \
  --model-name Qwen/Qwen2.5-Coder-0.5B-Instruct \
  --input-length 8192 \
  --label-length 64 \
  --batch-size 1 \
  --inference-batch-size "${TYPEPRO_INFERENCE_BATCH_SIZE:-1}" \
  --gradient-accumulation-steps 16 \
  --epochs 3 \
  --learning-rate 1e-4 \
  --mixed-precision fp16 \
  --attn-implementation sdpa \
  --gradient-checkpointing \
  --group-by-length \
  --length-cache \
  --length-log-every 1000 \
  --preview-samples 0 \
  --seed 13 \
  --log-every 50
