#!/usr/bin/env bash
# Deploy or update ShopBot publicly. Safe to re-run.
#   ./deploy.sh          server with a domain: Caddy on 80/443, automatic HTTPS (docs/DEPLOY.md)
#   ./deploy.sh tunnel   any machine with Docker: Cloudflare quick tunnel, prints a public URL
# First run also downloads the Ollama models, seeds demo data and builds the vector store.
set -euo pipefail
cd "$(dirname "$0")"

mode="${1:-https}"
[ -f .env ] || { echo "Missing .env: copy .env.example and fill it in (docs/DEPLOY.md)"; exit 1; }
grep -q '^GRAFANA_ADMIN_PASSWORD=.' .env || echo "GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 12)" >> .env
# Read only the non-secret values this script needs (never source .env: it holds secrets)
env_get() { { grep -E "^$1=" .env || true; } | tail -1 | cut -d= -f2- | tr -d '\r' | xargs; }
DOMAIN=$(env_get DOMAIN); POSTGRES_USER=$(env_get POSTGRES_USER); POSTGRES_DB=$(env_get POSTGRES_DB)

if [ "$mode" = tunnel ]; then
  export CLIENT_IP_HEADER=cf-connecting-ip  # real visitor IP for rate limiting
else
  [ -n "${DOMAIN:-}" ] || { echo "Set DOMAIN in .env (e.g. shopbot.duckdns.org)"; exit 1; }
  echo "==> Updating code"
  git pull --ff-only
fi
dc() { docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile "$mode" "$@"; }

echo "==> Building and starting services"
dc up -d --build --remove-orphans

echo "==> Waiting for Ollama models (first run downloads ~2.3 GB)"
until [ "$(dc ps -a --format '{{.State}}' ollama-pull)" = exited ]; do sleep 5; done

echo "==> Waiting for the gateway to be ready"
until dc exec -T gateway python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/ready')" 2>/dev/null; do
  sleep 5
done

if ! dc exec -T postgres psql -U "${POSTGRES_USER:-shopbot}" -d "${POSTGRES_DB:-shopbot}" -tAc "select 1 from users limit 1" 2>/dev/null | grep -q 1; then
  echo "==> First deploy: seeding demo data and building the vector store"
  dc run --rm seed
  dc run --rm ingest
fi

if [ "$mode" = tunnel ]; then
  url=""
  until [ -n "$url" ]; do
    sleep 3
    url=$(dc logs cloudflared 2>/dev/null | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1 || true)
  done
  echo "==> Live at $url  (changes whenever the tunnel restarts; online while this machine runs)"
else
  echo "==> Live at https://${DOMAIN}"
fi
