#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "Error: virtualenv not found at ${VENV_DIR}. Run scripts/bootstrap_env.sh first." >&2
  exit 1
fi

# shellcheck source=/dev/null
source "${VENV_DIR}/bin/activate"

python - <<'PY'
import importlib
modules = ["agentic_sizing", "langgraph", "numpy", "openai", "yaml"]
for m in modules:
    ok = importlib.util.find_spec(m) is not None
    print(f"{m}: {'OK' if ok else 'MISSING'}")
PY

cd "${ROOT_DIR}"
pytest
