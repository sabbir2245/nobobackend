#!/usr/bin/env bash
# Create the PostgreSQL user + database for the Nobanno backend.
# Reads credentials from .env (defaults match .env.example). Idempotent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Safely load values from .env if present
if [ -f ".env" ]; then
  while IFS='=' read -r key value || [ -n "$key" ]; do
    # Skip comments and blank lines
    [[ "$key" =~ ^[[:space:]]*# ]] && continue
    [[ -z "$key" ]] && continue
    
    # Clean leading/trailing spaces and quotes
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
    
    if [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      export "$key=$value"
    fi
  done < .env
fi

# Set fallback defaults
DB_NAME="${DB_NAME:-nobanno_db}"
DB_USER="${DB_USER:-nobanno_user}"
DB_PASSWORD="${DB_PASSWORD:-pass}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"

echo "==> Creating PostgreSQL role '$DB_USER' and database '$DB_NAME' on $DB_HOST:$DB_PORT (if not exist)"

# 1. Create Role & Create Database if missing
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
      CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';
   ELSE
      ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';
   END IF;
END
\$\$;

SELECT 'CREATE DATABASE ' || quote_ident('${DB_NAME}') || ' OWNER ' || quote_ident('${DB_USER}')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_NAME}')\gexec
SQL

# 2. Ensure Database Ownership & Privileges
sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER DATABASE ${DB_NAME} OWNER TO ${DB_USER};"
sudo -u postgres psql -v ON_ERROR_STOP=1 -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"

echo "==> Done. Verifying connection:"
PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
  -c "SELECT current_user, current_database();"