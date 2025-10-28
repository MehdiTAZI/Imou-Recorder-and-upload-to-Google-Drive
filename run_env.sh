#!/usr/bin/env bash
set -euo pipefail

VENV_DIR=".venv"
PYTHON_BIN="$(command -v python3 || true)"

if [[ -z "$PYTHON_BIN" ]]; then
  echo "python3 introuvable. Veuillez installer Python 3." >&2
  exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  echo "Environnement virtuel créé dans $VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
VENV_PYTHON="$VENV_DIR/bin/python"
"$VENV_PYTHON" -m pip install --upgrade pip

if [[ -f "requirements.txt" ]]; then
  "$VENV_PYTHON" -m pip install -r requirements.txt
else
  echo "requirements.txt introuvable. Installer les dépendances manuellement." >&2
  exit 1
fi

echo "Environnement prêt. Utilisez: source $VENV_DIR/bin/activate"
