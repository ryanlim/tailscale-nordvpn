#!/bin/bash

INTERFACE_LOCAL=eth0

# Detect the NordVPN tunnel interface in priority order:
#   1. NORDVPN_INTERFACE if explicitly provided
#   2. nordlynx  (NordLynx / WireGuard mode)
#   3. nordtun   (OpenVPN mode)
detect_nordvpn_interface() {
  if [ -n "${NORDVPN_INTERFACE:-}" ]; then
    echo "$NORDVPN_INTERFACE"
    return
  fi
  if ip -brief addr show nordlynx > /dev/null 2>&1; then
    echo "nordlynx"
    return
  fi
  if ip -brief addr show nordtun > /dev/null 2>&1; then
    echo "nordtun"
    return
  fi
  echo ""
}

# Add a rule only if it does not already exist (prevents duplicate rules on reconnect).
ensure_rule() {
  iptables -C "$@" 2>/dev/null || iptables -A "$@"
}

# Remove a rule only if it exists.
delete_rule() {
  if iptables -C "$@" 2>/dev/null; then
    iptables -D "$@"
  fi
}

INTERFACE_NORD=$(detect_nordvpn_interface)

if [ -z "$INTERFACE_NORD" ]; then
  echo "NordVPN tunnel interface not found (tried NORDVPN_INTERFACE, nordlynx, nordtun). Is NordVPN running?"
  exit 1
fi

echo "Using NordVPN interface: $INTERFACE_NORD"

if [ "x$1" == "xadd" ]; then
  set -x
  ensure_rule -t nat POSTROUTING -o "$INTERFACE_NORD" -j MASQUERADE
  ensure_rule INPUT -i "$INTERFACE_LOCAL" -j ACCEPT
  ensure_rule FORWARD -i "$INTERFACE_LOCAL" -o "$INTERFACE_NORD" -j ACCEPT
  ensure_rule FORWARD -i "$INTERFACE_NORD" -o "$INTERFACE_LOCAL" -j ACCEPT
  set +x
elif [ "x$1" == "xdel" ]; then
  set -x
  delete_rule -t nat POSTROUTING -o "$INTERFACE_NORD" -j MASQUERADE
  delete_rule INPUT -i "$INTERFACE_LOCAL" -j ACCEPT
  delete_rule FORWARD -i "$INTERFACE_LOCAL" -o "$INTERFACE_NORD" -j ACCEPT
  delete_rule FORWARD -i "$INTERFACE_NORD" -o "$INTERFACE_LOCAL" -j ACCEPT
  set +x
else
  echo "$0 [add|del]"
  exit 1
fi

