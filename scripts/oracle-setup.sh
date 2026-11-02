#!/usr/bin/env bash
# One-time set-up of the always-on Thodara demo (ADR-0016, option B) on an Oracle Cloud
# "Always Free" Ubuntu VM. Run it on the VM, inside the cloned Thodara folder:
#
#   scripts/oracle-setup.sh <duckdns-name> <duckdns-token> <your-email>
#   e.g. scripts/oracle-setup.sh srimant-demo 1a2b3c4d-... you@example.com
#
# It installs Docker, opens ports 80/443 in the VM's own firewall, points
# <duckdns-name>.duckdns.org at this VM, starts the demo with HTTPS, and schedules a
# nightly backup and reset. Fictional data only. Safe to run again.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ $# -ne 3 ]; then
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
fi
NAME=$1 TOKEN=$2 EMAIL=$3
case "$NAME" in *.*|"") echo "Give only the DuckDNS name, e.g. srimant-demo (not .duckdns.org)" >&2; exit 2 ;; esac
HOST="$NAME.duckdns.org"
HERE=$(pwd)

echo "== 1. Docker"
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  sudo apt-get update -q
  sudo apt-get install -y -q ca-certificates curl
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update -q
  sudo apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
sudo usermod -aG docker "$USER"

echo "== 2. Firewall on the VM (Oracle's Ubuntu images block everything but SSH)"
for port in 443 80; do
  if ! sudo iptables -C INPUT -p tcp --dport "$port" -m conntrack --ctstate NEW -j ACCEPT 2>/dev/null; then
    sudo iptables -I INPUT 1 -p tcp --dport "$port" -m conntrack --ctstate NEW -j ACCEPT
  fi
done
if command -v netfilter-persistent >/dev/null; then
  sudo netfilter-persistent save
else
  echo "   netfilter-persistent not found; the rules last until the next reboot." >&2
fi
echo "   Also open TCP 80 and 443 in the Oracle console (Networking > VCN > Security List)."

echo "== 3. DuckDNS name -> this VM"
umask 077
printf '%s\n' "$TOKEN" > "$HOME/.duckdns-token"
cat > "$HOME/duckdns-update.sh" <<EOF
#!/bin/sh
# Keeps $HOST pointing at this VM (an empty ip= means "the address this request came from").
curl -fsS "https://www.duckdns.org/update?domains=$NAME&token=\$(cat "$HOME/.duckdns-token")&ip=" -o "$HOME/duckdns.last"
EOF
chmod 700 "$HOME/duckdns-update.sh"
"$HOME/duckdns-update.sh"
if [ "$(cat "$HOME/duckdns.last")" != "OK" ]; then
  echo "DuckDNS did not accept the update (check the name and token)." >&2
  exit 1
fi
echo "   $HOST now points here."

echo "== 4. Demo settings"
touch .env
chmod 600 .env
set_env() { grep -v "^$1=" .env > .env.tmp || true; printf '%s=%s\n' "$1" "$2" >> .env.tmp; mv .env.tmp .env; }
set_env DEMO_MODE cloud
set_env DEMO_HOST "$HOST"
set_env ACME_EMAIL "$EMAIL"

echo "== 5. Start (the first build takes several minutes)"
sg docker -c "scripts/demo.sh start"

echo "== 6. Schedule: DuckDNS every 10 minutes; backup + reset nightly at 02:30 IST"
( crontab -l 2>/dev/null | grep -v -e duckdns-update.sh -e 'demo.sh nightly' || true
  echo "*/10 * * * * $HOME/duckdns-update.sh"
  echo "0 21 * * * cd $HERE && scripts/demo.sh nightly >> $HOME/thodara-nightly.log 2>&1"
) | crontab -
echo
echo "Done. Demo: https://$HOST   Accounts: $HERE/demo-accounts.txt"
echo "The certificate can take a minute on first visit. Log out and in once so 'docker' works without sg."
