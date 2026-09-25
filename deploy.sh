#!/usr/bin/env bash
# Deploy or update ShopBot on a server. Safe to re-run: ./deploy.sh
# First run: builds images, pulls Ollama models, seeds demo data, builds the vector store.
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || { echo "Missing .env: copy .env.example and fill it in (docs/DEPLOY.md)"; exit 1; }
set -a; . ./.env; set +a
dc() { docker compose -f docker-compose.yml -f docker-compose.prod.yml "$@"; }

echo "==> Updating code"
git pull --ff-only

echo "==> Building and starting services"
dc up -d --build --remove-orphans

echo "==> Waiting for Ollama models (first run downloads ~2.3 GB)"
dc wait ollama-pull >/dev/null

echo "==> Waiting for the gateway to be ready"
until dc exec -T gateway python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/ready')" 2>/dev/null; do
  sleep 5
done

if ! dc exec -T postgres psql -U "${POSTGRES_USER:-shopbot}" -d "${POSTGRES_DB:-shopbot}" -tAc "select 1 from users limit 1" 2>/dev/null | grep -q 1; then
  echo "==> First deploy: seeding demo data and building the vector store"
  dc run --rm seed
  dc run --rm ingest
fi

echo "==> Live at https://${DOMAIN}"
