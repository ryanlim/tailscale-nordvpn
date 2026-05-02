#!/bin/sh

set -x

# Run any executable hooks dropped into /scripts (bind-mounted from the
# host's tailscale/scripts/) before bringing the daemon up. Useful for
# host-specific setup like installing certs or extra packages. Files
# missing the executable bit (e.g. README.txt) are skipped.
if [ -d /scripts ]; then
  for f in /scripts/*; do
    [ -f "$f" ] && [ -x "$f" ] && "$f"
  done
fi

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

choose_cert_files() {
  # Sets CERT_FILE / KEY_FILE to a coherent pair. If a real cert AND a
  # real key are present under /etc/nginx/cert (bind-mounted from
  # ./tailscale/cert/), use those. Otherwise generate self-signed stubs
  # into /etc/nginx/cert-stub so nginx still has something to serve and
  # HTTPS comes up — the bind-mount is read-only, so we can't write
  # there even when we want to.
  CERT_FILE=""
  for f in /etc/nginx/cert/fullchain.pem /etc/nginx/cert/cert.pem; do
    [ -f "$f" ] && CERT_FILE="$f" && break
  done
  KEY_FILE=""
  for f in /etc/nginx/cert/privkey.pem /etc/nginx/cert/key.pem; do
    [ -f "$f" ] && KEY_FILE="$f" && break
  done
  if [ -n "$CERT_FILE" ] && [ -n "$KEY_FILE" ]; then
    return
  fi

  STUB_DIR=/etc/nginx/cert-stub
  mkdir -p "$STUB_DIR"
  if [ ! -f "$STUB_DIR/fullchain.pem" ] || [ ! -f "$STUB_DIR/privkey.pem" ]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
      -subj "/CN=ts-tailscale-stub" \
      -keyout "$STUB_DIR/privkey.pem" \
      -out "$STUB_DIR/fullchain.pem"
    chmod 600 "$STUB_DIR/privkey.pem"
  fi
  CERT_FILE="$STUB_DIR/fullchain.pem"
  KEY_FILE="$STUB_DIR/privkey.pem"
}

write_nginx_config() {
  choose_cert_files

  CONF=/etc/nginx/http.d/panel.conf
  cat <<EOF >"$CONF"
server {
    listen 80;
    location / {
        proxy_pass http://${IP_PANEL}:80;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}

server {
    listen 443 ssl;
    http2 on;
    ssl_certificate     ${CERT_FILE};
    ssl_certificate_key ${KEY_FILE};
    location / {
        proxy_pass http://${IP_PANEL}:80;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
}

write_nginx_config
nginx -t && nginx

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
