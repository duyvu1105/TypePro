#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR=/home/anhnd_02/TypePro
DATA_DIR="$REPO_DIR/datasets/typepro-python-generative-v15"
PIPELINE_DIR="$REPO_DIR/codet5p_type_retrieval"
VENV_DIR="$REPO_DIR/.venv"
OUTPUT_DIR="$REPO_DIR/outputs/qwen25-coder-05b-8192"
CHECKPOINT="$OUTPUT_DIR/best"
PREDICTIONS="$OUTPUT_DIR/test_predictions.jsonl"
LOG_FILE="$OUTPUT_DIR/infer_tmux.log"

mkdir -p "$OUTPUT_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

echo
echo "===== TypePro inference started: $(date --iso-8601=seconds) ====="
echo "Checkpoint: $CHECKPOINT"
echo "Input: $DATA_DIR/test.jsonl"
echo "Predictions: $PREDICTIONS"
echo "Log: $LOG_FILE"

finish() {
  exit_code=$?
  echo "===== TypePro inference finished: $(date --iso-8601=seconds), exit=$exit_code ====="
}
trap finish EXIT

if [[ ! -d "$CHECKPOINT" ]]; then
  echo "Checkpoint chưa tồn tại; hãy chờ training tạo $CHECKPOINT" >&2
  exit 1
fi

export CUDA_VISIBLE_DEVICES=0
export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1
export HF_HOME=/home/anhnd_02/.cache/huggingface

cd "$REPO_DIR"
"$VENV_DIR/bin/python" -u "$PIPELINE_DIR/infer_generative.py" \
  --checkpoint "$CHECKPOINT" \
  --model-name Qwen/Qwen2.5-Coder-0.5B-Instruct \
  --input "$DATA_DIR/test.jsonl" \
  --output "$PREDICTIONS" \
  --input-length 8192 \
  --label-length 64 \
  --batch-size 2
