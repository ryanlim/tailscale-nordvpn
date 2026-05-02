#!/bin/sh

set -x

tailscaled &

sleep 10s
ps auxwwf

ip route del default
ip route add default via $IP_NORDVPN dev eth0

INSTANCE_NAME_=$(echo $INSTANCE_NAME | sed 's/_/-/g')

# Number of consecutive watchdog cycles where VPN is up but tailscale looks
# broken before we kick tailscale. 60s per cycle, so 2 = ~2 minutes.
UNHEALTHY_THRESHOLD=2

do_tailscale_up() {
  # Re-issued on watchdog recovery as well as initial start. Auth key only
  # passed if tailscale is currently logged out and TAILSCALE_AUTH_KEY is set.
  AUTH_KEY_ARG=""
  if [ -n "$TAILSCALE_AUTH_KEY" ] && tailscale status 2>&1 | grep -q "Logged out"; then
    AUTH_KEY_ARG="--auth-key $TAILSCALE_AUTH_KEY"
  fi

  if [ -n "$TAILSCALE_UP_LOGIN_SERVER" ]; then
    tailscale up --advertise-exit-node --hostname $INSTANCE_NAME_ --login-server $TAILSCALE_UP_LOGIN_SERVER $AUTH_KEY_ARG
  else
    tailscale up --advertise-exit-node --hostname $INSTANCE_NAME_ $AUTH_KEY_ARG
  fi
}

is_vpn_connected() {
  # Hit the VPN backend's status API. Empty/unreachable response counts as
  # "not connected" so we err on the side of NOT kicking tailscale when the
  # backend itself is down (captive portal, upstream outage, mid-reconnect).
  curl -fsS --max-time 5 "http://${IP_NORDVPN}/api/v1/status" 2>/dev/null \
    | grep -q '"status": *"Connected"'
}

is_tailscale_healthy() {
  tailscale status --peers=false >/dev/null 2>&1
}

do_tailscale_up

cat <<EOF >/etc/tinyproxy.conf
Port 80
Listen 0.0.0.0
Timeout 600
ReversePath "/" "http://${IP_PANEL}:80/"
EOF

tinyproxy -c /etc/tinyproxy.conf

nohup /usr/bin/node_exporter >/tmp/node_exporter.log 2>&1 &

UNHEALTHY_COUNT=0
while [ 1 ]; do
  sleep 60
  date

  pidof tailscaled >/dev/null || tailscaled &

  # Re-assert the default route in case it went missing.
  ip route show default | grep -q "via $IP_NORDVPN" \
    || ip route replace default via $IP_NORDVPN dev eth0

  if is_vpn_connected && ! is_tailscale_healthy; then
    UNHEALTHY_COUNT=$((UNHEALTHY_COUNT + 1))
    echo "tailscale unhealthy while VPN reports Connected (count=$UNHEALTHY_COUNT)"
    if [ "$UNHEALTHY_COUNT" -ge "$UNHEALTHY_THRESHOLD" ]; then
      echo "kicking tailscale"
      tailscale down 2>/dev/null
      sleep 2
      do_tailscale_up
      UNHEALTHY_COUNT=0
    fi
  else
    UNHEALTHY_COUNT=0
  fi
done
