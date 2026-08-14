#!/usr/bin/env bash
# Nobanno backend: install requirements and run the backend.
# Usage:
#   ./run_backend.sh                  # install deps if needed, then run
#   ./run_backend.sh --setup          # only install deps + migrate + geo, no server
#   ./run_backend.sh --seed           # WIPES the DB and loads full seed/demo data, then runs
#   ./run_backend.sh --seed --setup   # install deps + wipe DB + seed, no server
#   ./run_backend.sh --port=8001      # run on a custom port
#   ./run_backend.sh --host=127.0.0.1 # bind to a specific host
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV=".venv"
PY="${VENV}/bin/python"
PORT="8000"
HOST="0.0.0.0"
MODE="run"
DO_SEED=0

for arg in "$@"; do
  case "$arg" in
    --setup) MODE="setup" ;;
    --seed) DO_SEED=1 ;;
    --port=*) PORT="${arg#--port=}" ;;
    --host=*) HOST="${arg#--host=}" ;;
    -h|--help)
      echo "Usage: $0 [--setup] [--seed] [--port=8000] [--host=0.0.0.0]"
      echo ""
      echo "  --setup   install deps + migrate + import geo, then exit"
      echo "  --seed    WIPE the database and load full seed/demo data (destructive!)"
      exit 0
      ;;
  esac
done

if [ ! -x "${PY}" ]; then
  echo ">> Creating virtualenv at .venv"
  python3 -m venv "$VENV"
fi

echo ">> Installing requirements"
"${VENV}/bin/pip" install --upgrade pip --quiet
"${VENV}/bin/pip" install -r requirements.txt --quiet

echo ">> Running migrations"
"${PY}" manage.py migrate

echo ">> Importing geo data"
"${PY}" manage.py import_geo

if [ "$DO_SEED" = "1" ]; then
  echo ">> WARNING: seed_data wipes existing data (users/orders/areas/etc.)"
  echo ">> Running seed_data ..."
  "${PY}" manage.py seed_data
fi

echo ">> Collecting static files"
"${PY}" manage.py collectstatic --noinput 2>/dev/null || echo "   (collectstatic skipped)"

if [ "$MODE" = "setup" ]; then
  echo ">> Setup complete. Run './run_backend.sh' to start the server."
  exit 0
fi

echo ">> Starting backend at http://${HOST}:${PORT}"
echo "   Media (timage) served at: http://${HOST}:${PORT}/media/"
exec "${PY}" manage.py runserver "${HOST}:${PORT}"