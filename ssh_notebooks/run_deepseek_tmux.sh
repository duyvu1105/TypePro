#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="${TYPEPRO_REPO_DIR:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)}"
OUTPUT_DIR="${TYPEPRO_OUTPUT_DIR:-$REPO_DIR/outputs/deepseek}"
LOG_FILE="$OUTPUT_DIR/infer_tmux.log"

mkdir -p "$OUTPUT_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

echo
echo "===== DeepSeek inference started: $(date --iso-8601=seconds) ====="
echo "Input: ${TYPEPRO_DATA_DIR:-$REPO_DIR/datasets/typepro-python-generative-v19}/test.jsonl"
echo "Checkpoint: $OUTPUT_DIR/checkpoint.sqlite3"
echo "Log: $LOG_FILE"

finish() {
  exit_code=$?
  echo "===== DeepSeek inference finished: $(date --iso-8601=seconds), exit=$exit_code ====="
}
trap finish EXIT

cd "$REPO_DIR"
"$REPO_DIR/.venv/bin/python" -u ssh_notebooks/infer_deepseek.py \
  --input "${TYPEPRO_DATA_DIR:-$REPO_DIR/datasets/typepro-python-generative-v19}/test.jsonl" \
  --output-dir "$OUTPUT_DIR"
