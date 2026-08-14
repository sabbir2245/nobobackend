#!/usr/bin/env bash
# Nobanno one-shot server setup: Gunicorn + Nginx.
# Run ONCE on the server as a user with sudo. Idempotent (safe to re-run).
# Preconditions (already done): code synced to ~/codes/nobobackend, .venv + .env exist,
# Postgres DB created (postgreset.sh), migrations + geo imported (deploy.sh --no-run).
set -euo pipefail

PROJECT_DIR="/home/s/codes/nobobackend"
MEDIA_DIR="/home/s/timage"
DOMAIN="nobannoapp.online"
SITE_CONF="nginx-nobanno.conf"
SERVICE="gunicorn.service"

echo "==> [1/5] Verify project paths & install gunicorn"
if [ ! -e "$PROJECT_DIR/.venv/bin/python" ]; then
  echo "MISSING venv: $PROJECT_DIR/.venv"; exit 1
fi
if [ ! -e "$PROJECT_DIR/.env" ]; then
  echo "MISSING .env: $PROJECT_DIR/.env"; exit 1
fi
if [ ! -e "$PROJECT_DIR/.venv/bin/gunicorn" ]; then
  echo "   Installing gunicorn into venv..."
  "$PROJECT_DIR/.venv/bin/pip" install --quiet gunicorn
fi
echo "   OK"

echo "==> [2/5] Ensure media dir & make it readable by Nginx"
sudo mkdir -p "$MEDIA_DIR"
# Remove any leftover ACL on /home/s (no longer needed with TCP backend) that
# could mask execute permission for www-data.
sudo setfacl -b /home/s 2>/dev/null || true
# Nginx (www-data) serves /media/ directly from disk via alias, so it must be
# able to traverse /home/s and read the media dir.
sudo chmod o+x /home/s 2>/dev/null || true
sudo chmod -R o+rX "$MEDIA_DIR" 2>/dev/null || true
echo "   OK"

echo "==> [3/5] Collect static files"
"$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/manage.py" collectstatic --noinput 2>&1 | tail -1
sudo chmod -R o+rX "$PROJECT_DIR/staticfiles" 2>/dev/null || true
echo "   OK"

echo "==> [4/5] Install Gunicorn systemd service"
sudo cp "$PROJECT_DIR/$SERVICE" /etc/systemd/system/gunicorn.service
sudo systemctl daemon-reload
sudo systemctl enable gunicorn
# Stop any stray dev runserver before starting gunicorn (avoid port conflict not needed, socket-based)
sudo systemctl restart gunicorn
sudo systemctl --no-pager status gunicorn || true
echo "   OK"

echo "==> [5/5] Install Nginx site config"
sudo cp "$PROJECT_DIR/$SITE_CONF" "/etc/nginx/sites-available/$SITE_CONF"
sudo ln -sf "/etc/nginx/sites-available/$SITE_CONF" "/etc/nginx/sites-enabled/$SITE_CONF"
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
echo "   OK"

echo "==> [Final] Verify"
echo "   api:   $(curl -s -o /dev/null -w '%{http_code}' https://$DOMAIN/api/locations/?level=division)"
echo "   admin: $(curl -s -o /dev/null -w '%{http_code}' https://$DOMAIN/admin/)"
echo "   media: $(curl -s -o /dev/null -w '%{http_code}' https://$DOMAIN/media/banana_avg.jpg)"
echo ""
echo "Done. Your site is live at https://$DOMAIN"