#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Error: ${PYTHON_BIN} not found." >&2
  exit 1
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

# shellcheck source=/dev/null
source "${VENV_DIR}/bin/activate"

python -m pip install --upgrade pip
python -m pip install -e "${ROOT_DIR}[openai,dev]"

python - <<'PY'
import importlib
modules = ["agentic_sizing", "langgraph", "numpy", "openai", "yaml"]
missing = [m for m in modules if importlib.util.find_spec(m) is None]
if missing:
    raise SystemExit(f"Missing required modules after install: {missing}")
print("Environment bootstrap complete. Required modules are available.")
PY

echo "Done. Activate with: source ${VENV_DIR}/bin/activate"
