#!/bin/bash

INTERFACE_VPN=wg0
INTERFACE_LOCAL=eth0

if ! ip -brief addr show "$INTERFACE_VPN" > /dev/null 2>&1; then
  echo "Interface $INTERFACE_VPN is not up. Is WireGuard running?"
  exit 1
fi

if [ "x$1" == "xadd" ]; then
  set -x
  iptables -t nat -I POSTROUTING 1 -o "$INTERFACE_VPN" -j MASQUERADE
  iptables -I INPUT 1 -i "$INTERFACE_LOCAL" -j ACCEPT
  iptables -I FORWARD 1 -i "$INTERFACE_LOCAL" -o "$INTERFACE_VPN" -j ACCEPT
  iptables -I FORWARD 1 -i "$INTERFACE_VPN" -o "$INTERFACE_LOCAL" -j ACCEPT
  set +x
elif [ "x$1" == "xdel" ]; then
  set -x
  iptables -t nat -D POSTROUTING -o "$INTERFACE_VPN" -j MASQUERADE
  iptables -D INPUT -i "$INTERFACE_LOCAL" -j ACCEPT
  iptables -D FORWARD -i "$INTERFACE_LOCAL" -o "$INTERFACE_VPN" -j ACCEPT
  iptables -D FORWARD -i "$INTERFACE_VPN" -o "$INTERFACE_LOCAL" -j ACCEPT
  set +x
else
  echo "$0 [add|del]"
  exit
fi
