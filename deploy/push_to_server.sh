#!/usr/bin/env bash
# Run this on YOUR OWN machine, in a plain local terminal - NOT inside the
# SSH session you already have open to the server. It needs to read the
# project files from this checkout, which only exist on this machine.
#
# ONE-TIME (or whenever Dockerfile/docker-compose.yml/deploy/ themselves
# change) - after the pipeline is wired up, code changes ship via CI
# building and pushing a new image, not via this script. This just needs
# to get docker-compose.yml + Dockerfile onto the server once so
# deploy/docker-provision.sh has something to run.
#
# --delete mirrors exactly, so the excludes below matter: .env holds the
# live secrets generated ON the server (there's no local .env to overwrite
# it with anyway - only .env.example is tracked), and data/media/staticfiles
# are the bind-mounted database and uploads. Losing the --exclude on any of
# those would delete live data on the next push.
set -euo pipefail

SERVER="root@5.189.175.18"
REMOTE_DIR="/opt/payroll/app"

cd "$(dirname "$0")/.."   # repo root

echo "==> Ensuring $REMOTE_DIR exists on $SERVER"
ssh "$SERVER" "mkdir -p '$REMOTE_DIR'"

echo "==> rsyncing project to $SERVER:$REMOTE_DIR"
rsync -avz --delete \
  --exclude ".venv/" \
  --exclude "__pycache__/" \
  --exclude "*.pyc" \
  --exclude ".git/" \
  --exclude "db.sqlite3" \
  --exclude ".env" \
  --exclude "data/" \
  --exclude "media/" \
  --exclude "staticfiles/" \
  --exclude "cookies" \
  --exclude "cj" \
  --exclude "nextjs-ui-kit/" \
  ./ "$SERVER:$REMOTE_DIR/"

echo "==> Done. Next: SSH in and run deploy/docker-provision.sh (see deploy/README.md)."
