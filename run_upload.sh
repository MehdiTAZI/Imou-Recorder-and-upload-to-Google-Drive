#!/usr/bin/env bash
set -euo pipefail

VENV_DIR=".venv"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Virtualenv absent. Exécutez ./run_env.sh d'abord." >&2
  exit 1
fi

source "$VENV_DIR/bin/activate"
python upload_videos.py
