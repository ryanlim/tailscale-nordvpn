#!/bin/sh

set -eu

export PATH=/scripts:$PATH

log() {
  echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] $*"
}

fatal() {
  echo "ERROR: $*" >&2
  exit 1
}

: "${NORDVPN_TOKEN:?NORDVPN_TOKEN environment variable is unset.}"
: "${IP_SUBNET:?IP_SUBNET environment variable is unset.}"

RECONNECT_AFTER_HOURS="${RECONNECT_AFTER_HOURS:-1}"
case "$RECONNECT_AFTER_HOURS" in
  ''|*[!0-9]*)
    fatal "RECONNECT_AFTER_HOURS must be an integer number of hours."
    ;;
esac
RECONNECT_AFTER_SECONDS=$((RECONNECT_AFTER_HOURS * 60 * 60))

ENDPOINT="${NORDVPN_ENDPOINT:-San_Francisco}"
ENDPOINT_STATE="/tmp/nordvpn_connect_endpoint.txt"
TECHNOLOGY="$(printf '%s' "${NORDVPN_TECHNOLOGY:-openvpn}" | tr '[:upper:]' '[:lower:]')"
OPENVPN_PROTOCOL="$(printf '%s' "${NORDVPN_OPENVPN_PROTOCOL:-tcp}" | tr '[:upper:]' '[:lower:]')"

start_nordvpn_daemon() {
  log "Starting NordVPN daemon ..."
  /etc/init.d/nordvpn start
}

wait_for_nordvpn_daemon() {
  attempts=0
  while true; do
    if nordvpn status >/dev/null 2>&1; then
      return 0
    fi
    sleep 3

    attempts=$((attempts + 1))
    if [ "$attempts" -ge 3 ]; then
      log "NordVPN daemon is not responding. Restarting it ..."
      /etc/init.d/nordvpn stop || true
      start_nordvpn_daemon
      attempts=0
    fi
  done
}

nordvpn_connect() {
  attempts=0
  while [ "$attempts" -lt 3 ]; do
    if [ -f "$ENDPOINT_STATE" ]; then
      ENDPOINT_OVERRIDE="$(tr -d '\r\n' < "$ENDPOINT_STATE")"
      if [ -n "$ENDPOINT_OVERRIDE" ]; then
        ENDPOINT="$ENDPOINT_OVERRIDE"
      fi
    fi

    log "Connecting to NordVPN endpoint: $ENDPOINT"
    if nordvpn connect "$ENDPOINT"; then
      bash /scripts/iptables_rules.sh add
      return 0
    fi

    attempts=$((attempts + 1))
    if [ "$attempts" -lt 3 ]; then
      log "NordVPN connect failed. Retrying ..."
      sleep 1
    fi
  done

  return 1
}

start_nordvpn_daemon

wait_for_nordvpn_daemon

log "Disabling NordVPN analytics ..."
nordvpn set analytics off

if ! nordvpn account >/dev/null 2>&1; then
  log "No active NordVPN session detected. Logging in with token ..."
  nordvpn login --token "$NORDVPN_TOKEN"
fi

log "Configuring NordVPN technology: $TECHNOLOGY"
nordvpn set technology "$TECHNOLOGY"
if [ "$TECHNOLOGY" = "openvpn" ]; then
  log "Configuring OpenVPN protocol: $OPENVPN_PROTOCOL"
  nordvpn set protocol "$OPENVPN_PROTOCOL"
fi

if nordvpn allowlist list 2>/dev/null | grep -F "$IP_SUBNET" >/dev/null 2>&1; then
  log "Local subnet $IP_SUBNET is already allowlisted."
else
  log "Allowlisting local subnet $IP_SUBNET"
  nordvpn allowlist add subnet "$IP_SUBNET"
fi

log "Enabling autoconnect"
nordvpn set autoconnect on

log "Enabling kill switch"
nordvpn set killswitch on

if ! nordvpn_connect; then
  fatal "Cannot connect to NordVPN after multiple attempts."
fi

log "Reconnect period: ${RECONNECT_AFTER_SECONDS}s"

while true; do
  sleep "$RECONNECT_AFTER_SECONDS"
  log "Rotating NordVPN server"
  bash /scripts/iptables_rules.sh del
  if ! nordvpn disconnect; then
    log "NordVPN disconnect returned a non-zero status. Continuing with reconnect."
  fi
  sleep 1
  if ! nordvpn_connect; then
    fatal "Cannot reconnect to NordVPN after multiple attempts."
  fi
done
