#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR=/home/anhnd_02/TypePro
DATA_DIR="$REPO_DIR/datasets/typepro-python-generative"
PIPELINE_DIR="$REPO_DIR/codet5p_type_retrieval"
VENV_DIR="$REPO_DIR/.venv"
OUTPUT_DIR="$REPO_DIR/outputs/qwen25-coder-05b-8192"
LOG_FILE="$OUTPUT_DIR/train_tmux.log"

mkdir -p "$OUTPUT_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

echo
echo "===== TypePro training started: $(date --iso-8601=seconds) ====="
echo "Log: $LOG_FILE"

finish() {
  exit_code=$?
  echo "===== TypePro training finished: $(date --iso-8601=seconds), exit=$exit_code ====="
}
trap finish EXIT

export CUDA_VISIBLE_DEVICES=0
export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1
export HF_HOME=/home/anhnd_02/.cache/huggingface

cd "$REPO_DIR"
"$VENV_DIR/bin/accelerate" launch \
  --num_machines 1 \
  --num_processes 1 \
  --mixed_precision fp16 \
  "$PIPELINE_DIR/train_generative.py" \
  --data-dir "$DATA_DIR" \
  --output-dir "$OUTPUT_DIR" \
  --model-name Qwen/Qwen2.5-Coder-0.5B-Instruct \
  --input-length 8192 \
  --label-length 128 \
  --batch-size 1 \
  --gradient-accumulation-steps 16 \
  --epochs 3 \
  --learning-rate 2e-5 \
  --mixed-precision fp16 \
  --attn-implementation sdpa \
  --gradient-checkpointing \
  --group-by-length \
  --length-cache \
  --length-log-every 1000 \
  --seed 13 \
  --log-every 10
