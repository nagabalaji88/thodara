#!/usr/bin/env bash
# Thodara demo hosting (ADR-0016): fictional data, reachable through a free Cloudflare
# quick tunnel. Usage: scripts/demo.sh start|url|reset|backup|stop
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE=(docker compose -p thodara-demo -f compose.yaml -f compose.demo.yaml)

ensure_env() {
  if [ ! -f .env ]; then
    echo "Creating .env with a random database password..."
    pass=$(python3 -c "import secrets;print(secrets.token_hex(16))")
    printf 'POSTGRES_DB=thodara\nPOSTGRES_USER=thodara\nPOSTGRES_PASSWORD=%s\n' "$pass" > .env
    chmod 600 .env
  fi
  if ! grep -q '^THODARA_TWO_STEP_KEY=' .env; then
    echo "Adding a private two-step key to .env (keep this file)..."
    key=$(python3 -c "import base64,secrets;print(base64.b64encode(secrets.token_bytes(32)).decode())")
    printf 'THODARA_TWO_STEP_KEY=%s\n' "$key" >> .env
  fi
  set -a; . ./.env; set +a
}

user_count() {
  "${COMPOSE[@]}" exec -T db psql -U "${POSTGRES_USER:-thodara}" -d "${POSTGRES_DB:-thodara}" -tAc "select count(*) from users" | tr -d '[:space:]'
}

seed() {
  # The passwords are shown once and kept in demo-accounts.txt on this computer only.
  "${COMPOSE[@]}" exec -T api /app/.venv/bin/thodara-api seed-demo "$@" | tee demo-accounts.txt
  chmod 600 demo-accounts.txt
}

tunnel_url() {
  for _ in $(seq 1 30); do
    url=$("${COMPOSE[@]}" logs tunnel 2>/dev/null | grep -oE 'https://[a-z0-9]+(-[a-z0-9]+)+\.trycloudflare\.com' | tail -1 || true)
    if [ -n "$url" ]; then echo "$url"; return 0; fi
    sleep 2
  done
  echo "The tunnel did not report an address; see: ${COMPOSE[*]} logs tunnel" >&2
  return 1
}

case "${1:-}" in
  start)
    ensure_env
    "${COMPOSE[@]}" up -d --wait db
    "${COMPOSE[@]}" run --rm --build migrate
    "${COMPOSE[@]}" up -d --build --wait api web
    if [ "$(user_count)" = "0" ]; then seed; fi
    "${COMPOSE[@]}" up -d tunnel
    url=$(tunnel_url)
    echo
    echo "Demo address (changes every time the tunnel restarts): $url"
    echo "Accounts and passwords: demo-accounts.txt"
    ;;
  reset)
    ensure_env
    seed --reset
    ;;
  backup)
    ensure_env
    mkdir -p backups
    file="backups/thodara-$(date +%Y%m%d-%H%M).dump"
    "${COMPOSE[@]}" exec -T db pg_dump -U "${POSTGRES_USER:-thodara}" -d "${POSTGRES_DB:-thodara}" -Fc > "$file"
    echo "Saved $file"
    ;;
  url)
    ensure_env
    tunnel_url
    ;;
  stop)
    ensure_env
    "${COMPOSE[@]}" stop tunnel
    "${COMPOSE[@]}" stop
    echo "Stopped. The demo address no longer works; data is kept."
    ;;
  *)
    echo "Usage: $0 start|url|reset|backup|stop" >&2
    exit 2
    ;;
esac
