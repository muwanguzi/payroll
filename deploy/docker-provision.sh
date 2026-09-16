#!/usr/bin/env bash
# ONE-TIME setup, run ON THE SERVER in your already-open root terminal.
# After this, the GitHub Actions pipeline (.github/workflows/ci-cd.yml)
# does every future deploy by itself - push to main, it builds, pushes to
# GHCR, and runs `docker compose up -d` here over SSH.
#
# Safe to re-run (e.g. if you need to redo the web-server step) - it won't
# recreate things that already exist, and never touches an existing Caddy/
# nginx site block that isn't ours.
#
# Web-server detection: same reasoning as the old bare-metal provision.sh -
# this box may already run Caddy or nginx for other sites (e.g. the main
# nextmedia.co.ug site), so this never blindly installs nginx on top of
# something else:
#   - Caddy already running  -> adds a new, additive site block (backed up,
#     validated, rolled back automatically if validation fails). Caddy then
#     gets its own cert automatically - no certbot needed.
#   - nginx already running / nothing on 80+443 -> installs nginx (if
#     needed) and adds a new vhost file; you run certbot yourself after,
#     once DNS is confirmed (see deploy/README.md).
#   - Something else owns 80/443 -> stops and tells you, touches nothing.
set -euo pipefail

APP_DIR="/opt/payroll/app"
DOMAIN="payroll.nextmedia.co.ug"
UPSTREAM="127.0.0.1:8001"
APP_UID=1000   # must match the `payroll` user's UID baked into the Dockerfile

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this as root." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 1. Docker itself
# ---------------------------------------------------------------------------
if ! command -v docker >/dev/null; then
  echo "==> Installing Docker Engine"
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# 2. App directory - docker-compose.yml + .env must already be here.
#    (pushed once via `bash deploy/push_to_server.sh` from your local
#    machine - see deploy/README.md)
# ---------------------------------------------------------------------------
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
  sed -i "s#^IMAGE=.*#IMAGE=payroll:local#" .env   # placeholder - the pipeline overwrites this on first automated deploy
  chmod 600 .env
  echo "    generated a real SECRET_KEY into $APP_DIR/.env (server-only, never in git)"
  echo "    IMAGE is a placeholder until the pipeline's first successful deploy - or set it"
  echo "    yourself to ghcr.io/<owner>/<repo>:latest and 'docker login ghcr.io' to pull now."
else
  echo "==> .env already exists, leaving it as-is"
fi

echo "==> Data directories (owned by uid $APP_UID to match the container's user)"
mkdir -p "$APP_DIR/data" "$APP_DIR/media" "$APP_DIR/staticfiles"
chown -R "$APP_UID":"$APP_UID" "$APP_DIR/data" "$APP_DIR/media" "$APP_DIR/staticfiles"

echo "==> First container start (builds locally if IMAGE isn't pullable yet)"
if ! docker compose pull 2>/dev/null; then
  echo "    couldn't pull $IMAGE yet (expected before the first pipeline run) - building locally instead"
  docker compose build
fi
docker compose up -d
sleep 2
if ! docker compose ps --status running --services | grep -q web; then
  echo "!! the web container did not start - check: docker compose logs web" >&2
  exit 1
fi
echo "    payroll is up on $UPSTREAM"

# ---------------------------------------------------------------------------
# 3. Web-server layer - detect before touching anything.
# ---------------------------------------------------------------------------
echo "==> Detecting what's already serving :80 / :443"
PORT80_OWNER=""; PORT443_OWNER=""
if command -v ss >/dev/null; then
  PORT80_OWNER="$(ss -tlnp 2>/dev/null | grep -E ':80\s' | grep -oP '(?<=users:\(\(")[^"]+' | head -1 || true)"
  PORT443_OWNER="$(ss -tlnp 2>/dev/null | grep -E ':443\s' | grep -oP '(?<=users:\(\(")[^"]+' | head -1 || true)"
fi
CADDY_ACTIVE="$(systemctl is-active caddy 2>/dev/null || true)"
NGINX_ACTIVE="$(systemctl is-active nginx 2>/dev/null || true)"
echo "    :80 owned by '${PORT80_OWNER:-<nothing>}', :443 owned by '${PORT443_OWNER:-<nothing>}'"
echo "    caddy service: ${CADDY_ACTIVE:-not installed} · nginx service: ${NGINX_ACTIVE:-not installed}"

configure_caddy() {
  echo "==> Caddy is running - adding an additive site block for $DOMAIN"
  local CADDYFILE="/etc/caddy/Caddyfile"
  if [ ! -f "$CADDYFILE" ]; then
    echo "!! caddy is active but $CADDYFILE not found - not guessing further. Add manually:" >&2
    echo "     $DOMAIN { reverse_proxy $UPSTREAM }" >&2
    return 1
  fi
  if grep -q "$DOMAIN" "$CADDYFILE" 2>/dev/null; then
    echo "    $DOMAIN already present in $CADDYFILE - leaving it as-is."
    return 0
  fi

  local BLOCK
  BLOCK=$(cat <<EOF

# --- Next Media Payroll (added by deploy/docker-provision.sh) ---
$DOMAIN {
	encode gzip
	handle_path /static/* {
		root * $APP_DIR/staticfiles
		file_server
	}
	handle_path /media/* {
		root * $APP_DIR/media
		file_server
	}
	reverse_proxy $UPSTREAM
}
EOF
)

  local IMPORT_DIR
  IMPORT_DIR="$(grep -oP '(?<=^import\s)\S+' "$CADDYFILE" | head -1 | xargs -r dirname 2>/dev/null || true)"
  if [ -n "$IMPORT_DIR" ] && [ -d "$IMPORT_DIR" ]; then
    echo "    using existing import directory: $IMPORT_DIR"
    echo "$BLOCK" > "$IMPORT_DIR/payroll.caddy"
  else
    local BACKUP="/etc/caddy/Caddyfile.bak-$(date +%Y%m%d%H%M%S)"
    cp "$CADDYFILE" "$BACKUP"
    echo "    backed up existing Caddyfile to $BACKUP, appending new block"
    echo "$BLOCK" >> "$CADDYFILE"
  fi

  if caddy validate --config "$CADDYFILE" >/dev/null 2>&1; then
    systemctl reload caddy
    echo "    caddy reloaded - it will fetch its own Let's Encrypt cert for $DOMAIN automatically."
    echo "    NO certbot step needed for the Caddy path."
  else
    echo "!! caddy validate failed - rolling back, touching nothing else:" >&2
    caddy validate --config "$CADDYFILE" 2>&1 | sed 's/^/    /' >&2
    if [ -n "${BACKUP:-}" ]; then cp "$BACKUP" "$CADDYFILE"; fi
    [ -f "${IMPORT_DIR:-/nonexistent}/payroll.caddy" ] && rm -f "$IMPORT_DIR/payroll.caddy"
    return 1
  fi
}

configure_nginx() {
  echo "==> Configuring nginx for $DOMAIN"
  if ! command -v nginx >/dev/null; then
    apt-get update -qq && apt-get install -y nginx >/dev/null
  fi
  cat > /etc/nginx/sites-available/payroll <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    client_max_body_size 20M;

    location /static/ {
        alias $APP_DIR/staticfiles/;
    }
    location /media/ {
        alias $APP_DIR/media/;
    }

    location / {
        proxy_pass http://$UPSTREAM;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  ln -sf /etc/nginx/sites-available/payroll /etc/nginx/sites-enabled/payroll
  if nginx -t 2>&1 | sed 's/^/    /'; then
    systemctl enable --now nginx >/dev/null 2>&1 || true
    systemctl reload nginx
    echo "    nginx reloaded. Once DNS resolves here, run certbot (see deploy/README.md)."
  else
    echo "!! nginx -t failed - removing the vhost we just added, touching nothing else:" >&2
    rm -f /etc/nginx/sites-enabled/payroll
    return 1
  fi
}

WEB_SERVER_OK=1
if [ "$CADDY_ACTIVE" = "active" ]; then
  configure_caddy || WEB_SERVER_OK=0
elif [ "$NGINX_ACTIVE" = "active" ] || { [ -z "$PORT80_OWNER" ] && [ -z "$PORT443_OWNER" ]; }; then
  configure_nginx || WEB_SERVER_OK=0
else
  echo "!! Ports 80/443 are owned by '$PORT80_OWNER'/'$PORT443_OWNER', which isn't caddy or nginx." >&2
  echo "   Not touching web-server config - the app is running on $UPSTREAM though." >&2
  echo "   Point whatever is already fronting this box at $UPSTREAM manually, or tell me what" >&2
  echo "   it is and I'll adapt this script." >&2
  WEB_SERVER_OK=0
fi

echo
echo "==> Done."
echo "    Check the app:       docker compose -f $APP_DIR/docker-compose.yml ps"
echo "    Check the app logs:  docker compose -f $APP_DIR/docker-compose.yml logs -f web"
if [ "$WEB_SERVER_OK" -eq 0 ]; then
  echo
  echo "!! The web-server step did not complete - see the error above. The app itself IS"
  echo "   running fine on $UPSTREAM; it's just not reachable from the internet yet."
fi
echo
echo "Still to do:"
echo "  - If IMAGE in .env is still the 'payroll:local' placeholder: add GitHub Actions"
echo "    secrets DEPLOY_HOST / DEPLOY_USER / DEPLOY_SSH_KEY and push to main - the"
echo "    pipeline will build the real image and flip IMAGE over automatically."
echo "  - If the nginx path ran: apt-get install -y certbot python3-certbot-nginx"
echo "    && certbot --nginx -d $DOMAIN   (once DNS resolves here)"
echo "  - If the caddy path ran: nothing else - it auto-provisions HTTPS."
echo "  - Create an admin login:"
echo "      docker compose exec web python manage.py createsuperuser"
