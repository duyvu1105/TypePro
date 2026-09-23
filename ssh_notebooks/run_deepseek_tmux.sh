#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR=/home/anhnd_02/TypePro
OUTPUT_DIR="$REPO_DIR/outputs/deepseek-flash-v15"
LOG_FILE="$OUTPUT_DIR/infer_tmux.log"

mkdir -p "$OUTPUT_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

echo
echo "===== DeepSeek inference started: $(date --iso-8601=seconds) ====="
echo "Input: $REPO_DIR/datasets/typepro-python-generative-v15/test.jsonl"
echo "Checkpoint: $OUTPUT_DIR/checkpoint.sqlite3"
echo "Log: $LOG_FILE"

finish() {
  exit_code=$?
  echo "===== DeepSeek inference finished: $(date --iso-8601=seconds), exit=$exit_code ====="
}
trap finish EXIT

cd "$REPO_DIR"
"$REPO_DIR/.venv/bin/python" -u ssh_notebooks/infer_deepseek.py \
  --input "$REPO_DIR/datasets/typepro-python-generative-v15/test.jsonl" \
  --output-dir "$OUTPUT_DIR"
