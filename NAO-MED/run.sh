#!/usr/bin/env bash
# NAO-Med launcher for Linux. Simulation only: never probes a physical NAO.
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$PROJECT_DIR/src"
if [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi
WEBOTS_PYENV_DIR="${NAOMED_WEBOTS_PYENV:-}"
PYTHON_BIN="${NAOMED_PYTHON:-${WEBOTS_PYENV_DIR:+$WEBOTS_PYENV_DIR/python}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ -x "$WEBOTS_PYENV_DIR/python" ]]; then
    # Webots resolves its controller interpreter through PATH.
    export PATH="$WEBOTS_PYENV_DIR:$PATH"
fi

usage() {
    echo "Usage: $0 {start|test|schedule}"
    echo "  start      Start the medication monitor and Webots"
    echo "  test       Send an immediate Paracetamol notification"
    echo "  schedule   Print the loaded medication schedule"
}

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "[ERROR] Python not found: $PYTHON_BIN" >&2
    echo "Set NAOMED_PYTHON to another Python executable if needed." >&2
    exit 1
fi

cd "$SRC_DIR"
export NAOMED_SIM_ONLY=1

case "${1:-}" in
    start)
        exec "$PYTHON_BIN" main.py
        ;;
    test)
        exec "$PYTHON_BIN" -c "from robot_connector import main as conectar; from nao_controller import notificar_medicamento; notificar_medicamento(conectar(), 'Paracetamol')"
        ;;
    schedule)
        exec "$PYTHON_BIN" schedule.py
        ;;
    *)
        usage
        exit 1
        ;;
esac
