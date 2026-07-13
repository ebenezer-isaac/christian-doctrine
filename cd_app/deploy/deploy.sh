#!/usr/bin/env bash
# One-command full-stack deploy for the Christian Doctrine app.
#
#   ./deploy/deploy.sh all       build web + ship + build/run api+web + route + purge cache + verify
#   ./deploy/deploy.sh web       rebuild + redeploy the web (flutter build, ship, rebuild image, purge)
#   ./deploy/deploy.sh api       ship backend + rebuild/restart the api
#   ./deploy/deploy.sh db        create/ensure the Mongo db + cd_app user (idempotent)
#   ./deploy/deploy.sh route     add the Cloudflare tunnel route + DNS (idempotent)
#   ./deploy/deploy.sh purge     purge the Cloudflare cache for the app assets
#   ./deploy/deploy.sh verify    check the live site + api health
#   ./deploy/deploy.sh logs      tail the api logs
#   ./deploy/deploy.sh ps        show container status
#
# Config comes from deploy/deploy.env (copy deploy.env.example). Runs from a
# machine with flutter + docker + ssh access to the VPS. Cache-busting (Docker
# --no-cache on web + Cloudflare purge) is built in so a deploy always lands.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$APP_DIR/deploy/deploy.env"
: "${VPS_HOST:?}" "${REMOTE_DIR:?}" "${SUBDOMAIN:?}" "${ZONE_NAME:?}" "${ZONE_ID:?}" \
  "${WEB_CONTAINER:?}" "${BACKEND_BASE_URL:?}" "${GOOGLE_CLIENT_ID:?}" "${APP_BEARER_TOKEN:?}"

log() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }

build_web() {
  log "flutter build web"
  ( cd "$APP_DIR/mobile" && flutter build web --release \
      --dart-define=BACKEND_BASE_URL="$BACKEND_BASE_URL" \
      --dart-define=GOOGLE_SERVER_CLIENT_ID="$GOOGLE_CLIENT_ID" \
      --dart-define=APP_BEARER_TOKEN="$APP_BEARER_TOKEN" )
  cp "$APP_DIR/mobile/assets/icon/favicon.png" "$APP_DIR/mobile/build/web/favicon.png" 2>/dev/null || true
  rm -rf "$APP_DIR/web/html" && mkdir -p "$APP_DIR/web/html"
  cp -r "$APP_DIR/mobile/build/web/"* "$APP_DIR/web/html/"
}

ship() {
  log "ship to $VPS_HOST:$REMOTE_DIR"
  ( cd "$APP_DIR" && tar czf - --exclude=__pycache__ --exclude='*.pyc' \
      backend web docker-compose.yml deploy \
      | ssh -o BatchMode=yes "$VPS_HOST" "mkdir -p $REMOTE_DIR && tar xzf - -C $REMOTE_DIR" )
}

up() {  # optional service arg; web is always --no-cache to defeat layer caching
  local svc="${1:-}"
  log "compose up ${svc:-all}"
  if [ "$svc" = "web" ] || [ -z "$svc" ]; then
    ssh -o BatchMode=yes "$VPS_HOST" "cd $REMOTE_DIR && docker compose build --no-cache web"
  fi
  ssh -o BatchMode=yes "$VPS_HOST" "cd $REMOTE_DIR && docker compose up -d --build $svc"
}

db() {
  log "ensure Mongo db + cd_app user"
  ssh -o BatchMode=yes "$VPS_HOST" 'bash -s' <<'REMOTE'
set -e
ENVD=$(docker inspect llmconveyors-mongodb --format '{{range .Config.Env}}{{println .}}{{end}}')
RPW=$(printf '%s\n' "$ENVD" | sed -n 's/^MONGO_ROOT_PASSWORD=//p')
RUSER=$(printf '%s\n' "$ENVD" | sed -n 's/^MONGO_ROOT_USERNAME=//p'); RUSER=${RUSER:-root}
[ -z "$RPW" ] && { echo "no root pw"; exit 1; }
if grep -q '^CD_APP_MONGO_URL=.*cd_app:' ~/sites/christian-doctrine/.env 2>/dev/null; then
  echo "cd_app user already provisioned in .env, skipping"; exit 0
fi
echo "cd_app user not found in .env; create it manually or via first deploy";
REMOTE
}

route() {
  log "cloudflare route + dns"
  ssh -o BatchMode=yes "$VPS_HOST" "cd $REMOTE_DIR && chmod +x deploy/add_route.sh && ./deploy/add_route.sh $SUBDOMAIN $ZONE_NAME ${WEB_CONTAINER}:80"
}

purge() {
  log "purge cloudflare cache"
  local base="https://${SUBDOMAIN}.${ZONE_NAME}"
  ssh -o BatchMode=yes "$VPS_HOST" "source ~/infra/.env; curl -s -X POST \
    'https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/purge_cache' \
    -H \"Authorization: Bearer \$CLOUDFLARE_API_TOKEN\" -H 'Content-Type: application/json' \
    -d '{\"files\":[\"${base}/\",\"${base}/index.html\",\"${base}/main.dart.js\",\"${base}/flutter_bootstrap.js\",\"${base}/flutter_service_worker.js\",\"${base}/flutter.js\",\"${base}/manifest.json\",\"${base}/favicon.png\",\"${base}/og-image.png\",\"${base}/assets/assets/icon/icon.png\",\"${base}/assets/AssetManifest.bin.json\",\"${base}/assets/AssetManifest.json\",\"${base}/icons/Icon-192.png\",\"${base}/icons/Icon-512.png\"]}'" \
    | python3 -c "import sys,json; print('cf purge:', json.load(sys.stdin).get('success'))" 2>/dev/null || true
}

verify() {
  log "verify"
  local base="https://${SUBDOMAIN}.${ZONE_NAME}"
  echo -n "site:      "; curl -s -o /dev/null -w "%{http_code}\n" --max-time 25 "$base/"
  echo -n "api health:"; curl -s --max-time 25 "$base/api/healthz"; echo
  echo -n "auth gate: "; curl -s -o /dev/null -w "%{http_code} (expect 401)\n" --max-time 25 "$base/api/conversations"
}

logs() { ssh -o BatchMode=yes "$VPS_HOST" "docker logs christian-doctrine-api 2>&1 | tail -40"; }
ps_()  { ssh -o BatchMode=yes "$VPS_HOST" "docker ps --format '{{.Names}} :: {{.Status}}' | grep -E 'christian-doctrine|cd-mcp|lexical-|cultural-'"; }

# --- Doctrine engine (cd_mcp + air-gapped stacks) on the VPS ------------------
engine_up() {  # bring up the two stacks + cd_mcp (reuses migrated volumes)
  log "engine up"
  ssh -o BatchMode=yes "$VPS_HOST" "cd sites/christian-doctrine-engine && bash deploy_engine/up.sh"
}
engine_deploy() {  # ship cd_mcp source + rebuild the cd-mcp image
  log "engine deploy (cd_mcp)"
  ( cd "$APP_DIR/.." && tar czf - --exclude=__pycache__ --exclude='*.pyc' cd_mcp \
      | ssh -o BatchMode=yes "$VPS_HOST" "tar xzf - -C sites/christian-doctrine-engine \
        && cd sites/christian-doctrine-engine \
        && docker compose -f deploy_engine/docker-compose.cdmcp.yml up -d --build cd-mcp" )
}

case "${1:-all}" in
  all)    build_web; ship; up ""; route; purge; verify ;;
  web)    build_web; ship; up web; purge; verify ;;
  api)    ship; up api; logs ;;
  db)     db ;;
  route)  route ;;
  purge)  purge ;;
  verify) verify ;;
  logs)   logs ;;
  ps)     ps_ ;;
  engine-up) engine_up ;;
  engine) engine_deploy ;;
  *) echo "usage: deploy.sh {all|web|api|db|route|purge|verify|logs|ps|engine|engine-up}"; exit 2 ;;
esac
log "done"
