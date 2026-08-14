# Nobanno Backend — VPS Deployment Guide

Detailed step-by-step instructions to get the Nobanno Django backend running on a
fresh Linux VPS (Ubuntu 22.04/24.04 LTS) with PostgreSQL, Gunicorn and Nginx.

---

## 1. Prerequisites (on your local machine)

- Git access to the repo, or a tarball/zip of the project.
- SSH access to the VPS (IP / user / key).
- A domain pointing to the VPS (recommended) OR the raw VPS IP.

---

## 2. Server overview

Production stack used by this project:

| Layer        | Tool                        |
|--------------|-----------------------------|
| Web server   | Nginx (reverse proxy / static) |
| App server   | Gunicorn (WSGI)             |
| Framework    | Django 5.2                  |
| Database     | PostgreSQL                  |
| Language     | Python 3.10+                |
| Payments     | bKash (sandbox by default)  |

---

## 3. Update the server & create a deploy user

```bash
sudo apt update && sudo apt upgrade -y
sudo adduser deploy
sudo usermod -aG sudo deploy
su - deploy
```

---

## 4. Install system packages

```bash
sudo apt install -y python3 python3-venv python3-pip \
  postgresql postgresql-contrib \
  nginx git curl \
  libpq-dev gcc build-essential
```

---

## 5. Install and configure PostgreSQL

```bash
sudo -u postgres psql
```

Inside the psql prompt:

```sql
CREATE USER nobanno_user WITH PASSWORD 'CHANGE_ME_STRONG_PASSWORD';
CREATE DATABASE nobanno_db OWNER nobanno_user;
GRANT ALL PRIVILEGES ON DATABASE nobanno_db TO nobanno_user;
\q
```

Create a PostgreSQL test database permission (used by `testing.py` / `manage.py test`):

```sql
ALTER USER nobanno_user CREATEDB;
```

> The backend uses `nobanno_db` / `nobanno_user`. Update `DB_*` in `.env` if you change names.

---

## 6. Upload the code

### Option A — Git clone (recommended)

```bash
su - deploy
cd ~
git clone <your-repo-url> upbackend
cd upbackend
```

### Option B — scp / rsync from local machine

```bash
# from your local machine
rsync -avz --exclude '.venv' --exclude 'db.sqlite3' --exclude '.env' \
  ./ upbackend deploy@<SERVER_IP>:~/upbackend/
```

> Do **not** copy `.venv`, `db.sqlite3` (SQLite is not used — PostgreSQL only), or a
> development `.env` with secrets.

---

## 7. Create the Python virtualenv & install requirements

```bash
cd ~/upbackend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> `psycopg2-binary` requires `libpq-dev` and `gcc` (installed in step 4).

---

## 8. Configure the environment (.env)

Start from the example and fill in real values:

```bash
cp .env.example .env
nano .env
```

Critical values to set:

```ini
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=<generate a long random string>

DJANGO_ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com,<SERVER_IP>

DB_NAME=nobanno_db
DB_USER=nobanno_user
DB_PASSWORD=CHANGE_ME_STRONG_PASSWORD
DB_HOST=localhost
DB_PORT=5432

EMAIL_HOST_USER=nobanno.contact@gmail.com
EMAIL_HOST_PASSWORD=CHANGE_ME

BKASH_SANDBOX=true
BKASH_CALLBACK_URL=https://yourdomain.com/api/payments/bkash/callback/
```

Generate a secret key:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

> `USE_SQLITE` is **removed** — the backend only uses PostgreSQL. Do not set it.

---

## 9. Run migrations & seed geo data

```bash
source .venv/bin/activate
python manage.py migrate
python manage.py import_geo
python manage.py collectstatic --noinput
```

- `migrate` creates all tables in PostgreSQL.
- `import_geo` loads divisions/districts/upazilas/unions (~4,500+ locations) from `geodata/`.
- `collectstatic` copies admin/jazzmin static files to `STATIC_ROOT` for Nginx.

Create an admin superuser (optional but recommended):

```bash
python manage.py createsuperuser
```

---

## 10. Test the server runs locally

```bash
python manage.py runserver 0.0.0.0:8000
# Ctrl+C when satisfied
```

If it starts without errors, the DB + env are correct.

---

## 11. Install & configure Gunicorn

Create a systemd service so Gunicorn auto-starts and restarts:

```bash
sudo nano /etc/systemd/system/gunicorn.service
```

```ini
[Unit]
Description=Gunicorn instance to serve Nobanno
After=network.target

[Service]
User=deploy
Group=deploy
WorkingDirectory=/home/deploy/upbackend
EnvironmentFile=/home/deploy/upbackend/.env
ExecStart=/home/deploy/upbackend/.venv/bin/gunicorn --workers 3 --bind unix:/home/deploy/upbackend/nobanno.sock nobanno.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable gunicorn
sudo systemctl start gunicorn
sudo systemctl status gunicorn
```

Tune `--workers` to `(2 × CPU cores) + 1`.

---

## 12. Configure Nginx

```bash
sudo nano /etc/nginx/sites-available/nobanno
```

```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com <SERVER_IP>;

    client_max_body_size 20M;

    # Static files (admin / jazzmin)
    location /static/ {
        alias /home/deploy/upbackend/staticfiles/;
    }

    # Media (uploaded post / review images)
    location /media/ {
        alias /home/deploy/upbackend/timage/;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/home/deploy/upbackend/nobanno.sock;
    }
}
```

Enable the site:

```bash
sudo ln -s /etc/nginx/sites-available/nobanno /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

Check logs if anything fails:

```bash
sudo tail -f /var/log/nginx/error.log
sudo journalctl -u gunicorn -n 50
```

---

## 13. Firewall & DNS

```bash
sudo ufw allow 'Nginx Full'
sudo ufw allow OpenSSH
sudo ufw enable
```

Point your domain's A record to the VPS IP. Then replace `http` with `https` via
Certbot:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
sudo certbot renew --dry-run
```

After HTTPS, update `BKASH_CALLBACK_URL` to `https://yourdomain.com/...` and restart gunicorn.

---

## 14. Verify the deployment

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://yourdomain.com/api/locations/?level=division
# expect 200

curl -s -o /dev/null -w "%{http_code}\n" http://yourdomain.com/admin/
# expect 200 (redirects/200)
```

Then run the full backend test suite on the server:

```bash
cd ~/upbackend
.venv/bin/python testing.py
```

> `testing.py` creates, uses and drops a throwaway Postgres test DB
> (`test_nobanno_db`), so it won't touch production data. It exercises the full
> flow including demo pay. Expect `RESULT: N passed, 0 failed`.

---

## 15. Optional — Cloudflare Tunnel (if you use it)

If you run behind Cloudflare Tunnel instead of exposing Nginx directly:

```ini
# in .env
CLOUDFLARE_TUNNEL_URL=https://your-tunnel.trycloudflare.com
```

Run `cloudflared tunnel` pointing at `http://localhost:8000` (or the socket), and
keep `BKASH_CALLBACK_URL` matching the public tunnel URL.

---

## 16. Common problems & fixes

| Problem                          | Fix |
|----------------------------------|-----|
| `could not connect to server`     | Verify Postgres is running: `sudo systemctl status postgresql`; check `DB_*` in `.env`. |
| `password authentication failed`  | Reset password: `ALTER USER nobanno_user WITH PASSWORD '...';` |
| `permission denied for database`  | Re-grant ownership: `GRANT ALL PRIVILEGES ON DATABASE nobanno_db TO nobanno_user;` |
| `Invalid HTTP_HOST header`        | Add the domain/IP to `DJANGO_ALLOWED_HOSTS`. |
| 502 Bad Gateway (Nginx)           | `sudo journalctl -u gunicorn -n 50`; ensure `.env` exists and socket path matches. |
| `select_for_update cannot be used outside of a transaction` | Only relevant to tests; the `deliver` endpoint was already fixed. |
| Static/admin CSS broken           | Re-run `python manage.py collectstatic --noinput` and check Nginx `/static/` alias. |
| Emails not sending                | Confirm `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` (Gmail app password) in `.env`. |

---

## 17. Quick reference (deploy commands)

```bash
# DB
sudo -u postgres psql -c "CREATE USER nobanno_user WITH PASSWORD 'CHANGE_ME_STRONG_PASSWORD';"
sudo -u postgres psql -c "CREATE DATABASE nobanno_db OWNER nobanno_user;"
sudo -u postgres psql -c "ALTER USER nobanno_user CREATEDB;"

# App
cd ~/upbackend
source .venv/bin/activate
python manage.py migrate
python manage.py import_geo
python manage.py collectstatic --noinput
python manage.py createsuperuser

# Gunicorn + Nginx
sudo systemctl restart gunicorn
sudo systemctl restart nginx
sudo systemctl status gunicorn
sudo systemctl status nginx
```

---

## 18. Post-deploy checklist

- [ ] `.env` present with production `DJANGO_SECRET_KEY` and strong DB password
- [ ] `DJANGO_DEBUG=false`
- [ ] Migrations applied
- [ ] Geo imported (`import_geo`)
- [ ] Static files collected and served by Nginx
- [ ] HTTPS enabled (Certbot)
- [ ] `BKASH_CALLBACK_URL` uses the public `https://` URL
- [ ] `testing.py` passes on the server
- [ ] Backups of the Postgres DB configured (e.g. `pg_dump` cron)