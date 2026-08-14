#!/usr/bin/env bash
# One-shot VPS deploy: install dependencies, configure .env, migrate, seed,
# collect static, then run the backend. Run from the cloned repo directory.
#
# Usage:
#   ./deploy.sh            # full setup, then run server on 0.0.0.0:8000
#   ./deploy.sh --seed     # full setup + wipe DB + load seed data, then run
#   ./deploy.sh --no-run   # setup only (no server) — good for first-time provisioning
#   ./deploy.sh --port=9000 --host=127.0.0.1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV=".venv"
PY="${VENV}/bin/python"
HOST="0.0.0.0"
PORT="8000"
DO_SEED=0
DO_RUN=1

for arg in "$@"; do
  case "$arg" in
    --seed) DO_SEED=1 ;;
    --no-run) DO_RUN=0 ;;
    --port=*) PORT="${arg#--port=}" ;;
    --host=*) HOST="${arg#--host=}" ;;
    -h|--help)
      echo "Usage: $0 [--seed] [--no-run] [--port=8000] [--host=0.0.0.0]"
      exit 0
      ;;
  esac
done

echo "==> [1/6] Python venv + requirements"
if [ ! -x "${PY}" ]; then
  python3 -m venv "$VENV"
fi
"${VENV}/bin/pip" install --upgrade pip --quiet
"${VENV}/bin/pip" install -r requirements.txt --quiet

echo "==> [2/6] Environment (.env)"
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "   Created .env from .env.example — EDIT .env with real DB/secret/email values before going live."
else
  echo "   .env already present."
fi

echo "==> [3/6] Migrations"
"${PY}" manage.py migrate

echo "==> [4/6] Import geo hierarchy"
"${PY}" manage.py import_geo

if [ "$DO_SEED" = "1" ]; then
  echo "==> [4b] Seeding demo data (WIPES existing rows)"
  "${PY}" manage.py seed_data
fi

echo "==> [5/6] Collect static files"
mkdir -p staticfiles
"${PY}" manage.py collectstatic --noinput || echo "   (collectstatic skipped)"

echo "==> [6/6] Create media dir"
mkdir -p timage/post_images timage/review_images

if [ "$DO_RUN" = "0" ]; then
  echo "Setup complete. Start the server with:  ./deploy.sh  (or via systemd/gunicorn)."
  exit 0
fi

echo "==> Starting backend at http://${HOST}:${PORT}"
exec "${PY}" manage.py runserver "${HOST}:${PORT}"