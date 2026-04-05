#!/bin/sh

set -eu

# Paths and configurable defaults
TAILSCALE_STATE_PATH="${TAILSCALE_STATE_PATH:-/var/lib/tailscale}"
TAILSCALE_SOCKET="${TAILSCALE_SOCKET:-/var/run/tailscale/tailscaled.sock}"
TAILSCALE_ETH_MTU="${TAILSCALE_ETH_MTU:-1385}"

# ---- helpers ----------------------------------------------------------------

wait_for_socket() {
  echo "Waiting for tailscaled socket at $TAILSCALE_SOCKET ..."
  i=0
  while [ ! -S "$TAILSCALE_SOCKET" ]; do
    sleep 1
    i=$((i + 1))
    if [ $i -ge 30 ]; then
      echo "ERROR: tailscaled socket did not appear after 30 seconds." >&2
      exit 1
    fi
  done
  echo "tailscaled socket is ready."
}

wait_for_gateway() {
  echo "Waiting for NordVPN gateway $IP_NORDVPN to become reachable ..."
  i=0
  while ! ping -c 1 -W 2 "$IP_NORDVPN" > /dev/null 2>&1; do
    sleep 2
    i=$((i + 1))
    if [ $i -ge 30 ]; then
      echo "ERROR: NordVPN gateway $IP_NORDVPN did not become reachable after 60 seconds." >&2
      exit 1
    fi
  done
  echo "NordVPN gateway $IP_NORDVPN is reachable."
}

set_eth_mtu() {
  echo "Setting eth0 MTU to $TAILSCALE_ETH_MTU ..."
  ip link set eth0 mtu "$TAILSCALE_ETH_MTU"
}

switch_default_route() {
  echo "Switching default route to NordVPN gateway $IP_NORDVPN ..."
  ip route del default || true
  ip route add default via "$IP_NORDVPN" dev eth0
}

run_tailscale_up() {
  INSTANCE_NAME_=$(echo "$INSTANCE_NAME" | sed 's/_/-/g')

  # Build argument list using positional parameters (POSIX sh has no arrays)
  set -- --advertise-exit-node --hostname "$INSTANCE_NAME_"

  if [ -n "${TAILSCALE_UP_LOGIN_SERVER:-}" ]; then
    set -- "$@" --login-server "$TAILSCALE_UP_LOGIN_SERVER"
  fi

  if [ -n "${TAILSCALE_AUTHKEY:-}" ]; then
    echo "Logging in with TAILSCALE_AUTHKEY ..."
    tailscale --socket "$TAILSCALE_SOCKET" up "$@" --authkey "$TAILSCALE_AUTHKEY"
  else
    echo "--------------------------------------------------------------"
    echo "No TAILSCALE_AUTHKEY set. Manual login required."
    echo "Run:  docker compose logs -f tailscale"
    echo "Then follow the URL printed below to authenticate."
    echo "--------------------------------------------------------------"
    tailscale --socket "$TAILSCALE_SOCKET" up "$@"
  fi
}

# ---- main -------------------------------------------------------------------

# Start tailscaled with explicit state and socket paths
mkdir -p "$(dirname "$TAILSCALE_SOCKET")"
tailscaled \
  --state "$TAILSCALE_STATE_PATH/tailscaled.state" \
  --socket "$TAILSCALE_SOCKET" &

wait_for_socket

set_eth_mtu

wait_for_gateway

switch_default_route

run_tailscale_up

# Health-check loop: restart tailscaled if it dies
while true; do
  sleep 60
  if ! pidof tailscaled > /dev/null 2>&1; then
    echo "tailscaled exited unexpectedly; restarting ..."
    tailscaled \
      --state "$TAILSCALE_STATE_PATH/tailscaled.state" \
      --socket "$TAILSCALE_SOCKET" &
    wait_for_socket
    run_tailscale_up
  fi
  date
done

