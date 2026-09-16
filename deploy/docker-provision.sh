#!/usr/bin/env bash
# ONE-TIME setup, run ON THE SERVER as root. After this, the GitHub Actions
# pipeline (.github/workflows/ci-cd.yml) does every future deploy by
# itself - push to main, it builds, pushes to GHCR, and runs
# `docker compose up -d` here over SSH.
#
# This server already runs Traefik (v3, Docker provider, network `proxy`,
# cert resolver `le`) in front of a large existing set of other company
# services - confirmed by inspecting it directly, not assumed. So unlike an
# earlier version of this script, there is NO nginx/Caddy install or
# detection here: docker-compose.yml already carries the Traefik labels and
# joins the `proxy` network, which is all Traefik needs to auto-route
# https://payroll.nextmedia.co.ug/ to this container and issue its own
# Let's Encrypt cert on first request. Nothing else on this box is touched.
set -euo pipefail

APP_DIR="/opt/payroll/app"
APP_UID=1000   # must match the `payroll` user's UID baked into the Dockerfile
TRAEFIK_NETWORK="proxy"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this as root." >&2
  exit 1
fi

if ! docker network inspect "$TRAEFIK_NETWORK" >/dev/null 2>&1; then
  echo "!! Docker network '$TRAEFIK_NETWORK' not found - expected it to already exist" >&2
  echo "   (created by the existing next_services/Traefik stack). Not proceeding blind:" >&2
  echo "   check 'docker network ls' and 'docker ps' to see what's actually running here." >&2
  exit 1
fi
echo "==> Found the existing '$TRAEFIK_NETWORK' network (Traefik's)"

if [ ! -f "$APP_DIR/docker-compose.yml" ]; then
  echo "!! $APP_DIR/docker-compose.yml not found." >&2
  echo "   Run deploy/push_to_server.sh from your LOCAL machine first." >&2
  exit 1
fi
cd "$APP_DIR"

if [ ! -f "$APP_DIR/.env" ]; then
  echo "==> Creating .env from .env.example"
  cp .env.example .env
  SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))' 2>/dev/null || docker run --rm python:3.14.4-slim-bookworm python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"
  sed -i "s#^DJANGO_SECRET_KEY=.*#DJANGO_SECRET_KEY=$SECRET_KEY#" .env
  sed -i "s#^IMAGE=.*#IMAGE=payroll:local#" .env   # placeholder until the pipeline's first successful deploy
  chmod 600 .env
  echo "    generated a real SECRET_KEY into $APP_DIR/.env (server-only, never in git)"
else
  echo "==> .env already exists, leaving it as-is"
fi

echo "==> Data directories (owned by uid $APP_UID to match the container's user)"
mkdir -p "$APP_DIR/data" "$APP_DIR/media" "$APP_DIR/staticfiles"
chown -R "$APP_UID":"$APP_UID" "$APP_DIR/data" "$APP_DIR/media" "$APP_DIR/staticfiles"

echo "==> First container start (builds locally if IMAGE isn't pullable yet)"
if ! docker compose pull 2>/dev/null; then
  echo "    couldn't pull yet (expected before the first pipeline run) - building locally instead"
  docker compose build
fi
docker compose up -d
sleep 2
if ! docker compose ps --status running --services | grep -q web; then
  echo "!! the web container did not start - check: docker compose logs web" >&2
  exit 1
fi
echo "    payroll container is up and on the '$TRAEFIK_NETWORK' network"

echo
echo "==> Done."
echo "    Check the app:       docker compose ps"
echo "    Check the app logs:  docker compose logs -f web"
echo "    Check Traefik picked it up:"
echo "      docker logs next_services-traefik-1 --tail 50 | grep -i payroll"
echo
echo "Still to do:"
echo "  - If IMAGE in .env is still the 'payroll:local' placeholder: add GitHub Actions"
echo "    secrets DEPLOY_HOST / DEPLOY_USER / DEPLOY_SSH_KEY and push to main - the"
echo "    pipeline will build the real image and flip IMAGE over automatically."
echo "  - DNS: payroll.nextmedia.co.ug must resolve to this server's IP before Traefik"
echo "    can complete the ACME HTTP-01 challenge and issue a cert."
echo "  - Create an admin login:"
echo "      docker compose exec web python manage.py createsuperuser"
