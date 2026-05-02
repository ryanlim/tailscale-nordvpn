#!/bin/bash
set -x

export PATH=/scripts:$PATH

PRIVATE_KEY_FILE=/etc/wireguard/private.key
TARGET_FILE=/etc/wireguard/.target

if [ ! -s "$PRIVATE_KEY_FILE" ]; then
  if [ -n "$NORDVPN_TOKEN" ]; then
    echo "$PRIVATE_KEY_FILE missing; extracting via NORDVPN_TOKEN."
    if ! /scripts/extract_key.sh > "$PRIVATE_KEY_FILE"; then
      rm -f "$PRIVATE_KEY_FILE"
      echo "ERROR: extract_key.sh failed. Sleeping so 'docker logs' shows this."
      sleep 60
      exit 1
    fi
  else
    echo "ERROR: $PRIVATE_KEY_FILE is missing or empty and NORDVPN_TOKEN is unset."
    echo "Either set NORDVPN_TOKEN in the environment, or extract the key manually:"
    echo "  ./nordvpn-wg/scripts/extract_key.sh > ./nordvpn-wg/wireguard/private.key"
    echo "Sleeping so 'docker logs' shows this; container will keep restarting."
    sleep 60
    exit 1
  fi
fi
chmod 600 "$PRIVATE_KEY_FILE"

RECONNECT_AFTER_HOURS=${RECONNECT_AFTER_HOURS:-1}
RECONNECT_AFTER_SECONDS=$((RECONNECT_AFTER_HOURS * 3600))

env

nohup python3 /webapp/app.py >/tmp/webapp.log 2>&1 &

trap 'nordvpn disconnect; exit 0' TERM INT

while true; do
  # Sticky target persists across restarts via TARGET_FILE; fall back to env.
  if [ -s "$TARGET_FILE" ]; then
    TARGET=$(cat "$TARGET_FILE")
  else
    TARGET=${NORDVPN_TARGET:-}
  fi

  if ! nordvpn connect "$TARGET"; then
    echo "Connect failed; retrying in 30s"
    sleep 30
    continue
  fi

  echo "Reconnect in ${RECONNECT_AFTER_SECONDS}s"
  sleep "$RECONNECT_AFTER_SECONDS"
  echo "--- $(date +%Y%m%d_%H%M%S) reconnecting ---"
  nordvpn disconnect || true
  sleep 1
done
