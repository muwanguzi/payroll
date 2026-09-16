#!/usr/bin/env bash
# Runs on every container start, before gunicorn. Idempotent - migrate and
# seed_reference are both safe to run repeatedly. Does NOT run seed_demo -
# no fake employees/pay runs in a real deploy.
set -euo pipefail

echo "[entrypoint] migrate"
python manage.py migrate --noinput

echo "[entrypoint] seed_reference (business units, codes, roles, PAYE/NSSF tables)"
python manage.py seed_reference

echo "[entrypoint] collectstatic"
python manage.py collectstatic --noinput >/dev/null

echo "[entrypoint] starting: $*"
exec "$@"
