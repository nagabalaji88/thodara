#!/usr/bin/env bash
# Thodara demo hosting (ADR-0016). Fictional data only.
#   Option A (default): this computer + a free Cloudflare quick tunnel (address changes).
#   Option B: an always-on server with HTTPS at DEMO_HOST, when .env has DEMO_MODE=cloud
#             (set up by scripts/oracle-setup.sh).
# Usage: scripts/demo.sh start|url|reset|new-passwords|backup|nightly|status|stop
set -euo pipefail
cd "$(dirname "$0")/.."
BACKUPS_KEPT=14

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
  if [ "${DEMO_MODE:-tunnel}" = "cloud" ]; then
    COMPOSE=(docker compose -p thodara-demo -f compose.yaml -f compose.demo.yaml -f compose.cloud.yaml)
    EDGE=caddy
  else
    COMPOSE=(docker compose -p thodara-demo -f compose.yaml -f compose.demo.yaml --profile tunnel)
    EDGE=tunnel
  fi
}

user_count() {
  "${COMPOSE[@]}" exec -T db psql -U "${POSTGRES_USER:-thodara}" -d "${POSTGRES_DB:-thodara}" -tAc "select count(*) from users" | tr -d '[:space:]'
}

seed() {
  # Passwords are shown once and kept in demo-accounts.txt on this computer only.
  local out
  out=$(mktemp)
  if [ "${1:-}" = "--keep" ]; then
    shift
    awk '/@srimant\.example\.com/ {print $2, $3}' demo-accounts.txt 2>/dev/null \
      | "${COMPOSE[@]}" exec -T api /app/.venv/bin/thodara-api seed-demo --keep-passwords "$@" > "$out"
  else
    "${COMPOSE[@]}" exec -T api /app/.venv/bin/thodara-api seed-demo "$@" < /dev/null > "$out"
  fi
  mv "$out" demo-accounts.txt
  chmod 600 demo-accounts.txt
  cat demo-accounts.txt
}

address() {
  if [ "$EDGE" = "caddy" ]; then
    echo "https://${DEMO_HOST}"
    return 0
  fi
  for _ in $(seq 1 30); do
    # Quick-tunnel names are hyphenated; this skips api.trycloudflare.com in error lines.
    url=$("${COMPOSE[@]}" logs tunnel 2>/dev/null | grep -oE 'https://[a-z0-9]+(-[a-z0-9]+)+\.trycloudflare\.com' | tail -1 || true)
    if [ -n "$url" ]; then echo "$url"; return 0; fi
    sleep 2
  done
  echo "The tunnel did not report an address; see: ${COMPOSE[*]} logs tunnel" >&2
  return 1
}

backup() {
  mkdir -p backups
  file="backups/thodara-$(date +%Y%m%d-%H%M).dump"
  "${COMPOSE[@]}" exec -T db pg_dump -U "${POSTGRES_USER:-thodara}" -d "${POSTGRES_DB:-thodara}" -Fc > "$file"
  chmod 600 "$file"
  # Keep the newest few; demo data can always be loaded again.
  ls -1t backups/thodara-*.dump | tail -n +$((BACKUPS_KEPT + 1)) | xargs -r rm --
  echo "Saved $file"
}

ensure_env
case "${1:-}" in
  start)
    "${COMPOSE[@]}" up -d --wait db
    "${COMPOSE[@]}" run --rm --build migrate
    "${COMPOSE[@]}" up -d --build --wait api web
    if [ "$(user_count)" = "0" ]; then seed > /dev/null; fi
    "${COMPOSE[@]}" up -d "$EDGE"
    echo
    echo "Demo address: $(address)"
    [ "$EDGE" = "tunnel" ] && echo "(It changes every time the tunnel restarts.)"
    echo "Accounts and passwords: demo-accounts.txt"
    ;;
  url) address ;;
  reset)
    # The story as new; the passwords already handed out keep working.
    seed --keep --reset
    ;;
  new-passwords) seed --reset ;;
  backup) backup ;;
  nightly)
    # For the always-on server: keep a copy, then restore the story (same passwords).
    backup
    seed --keep --reset > /dev/null
    echo "$(date -u +%FT%TZ) nightly reset done"
    ;;
  status) "${COMPOSE[@]}" ps ;;
  stop)
    "${COMPOSE[@]}" stop
    echo "Stopped. The demo address no longer works; data is kept."
    ;;
  *)
    echo "Usage: $0 start|url|reset|new-passwords|backup|nightly|status|stop" >&2
    exit 2
    ;;
esac
