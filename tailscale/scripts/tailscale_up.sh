#!/bin/sh

set -x

tailscaled &

sleep 10s
ps auxwwf

ip route del default
ip route add default via $IP_NORDVPN dev eth0

INSTANCE_NAME_=$(echo $INSTANCE_NAME | sed 's/_/-/g')

#tailscale up --advertise-exit-node --login-server https://headscale.limau.net
if [ -n "$TAILSCALE_UP_LOGIN_SERVER" ]; then
  LOGIN_SERVER="--login-server $TAILSCALE_UP_LOGIN_SERVER"
  tailscale up --advertise-exit-node --hostname $INSTANCE_NAME_ --login-server $TAILSCALE_UP_LOGIN_SERVER
else
  tailscale up --advertise-exit-node --hostname $INSTANCE_NAME_ $LOGIN_SERVER 
fi

apk add mtr curl prometheus-node-exporter tinyproxy

cat <<EOF > /etc/tinyproxy.conf
Port 80
Listen 0.0.0.0
Timeout 600
ReversePath "/" "http://${IP_NORDVPN}:80/"
EOF

tinyproxy -c /etc/tinyproxy.conf

nohup /usr/bin/node_exporter > /tmp/node_exporter.log 2>&1 &

while [ 1 ]; do
  sleep 60
  date
done
