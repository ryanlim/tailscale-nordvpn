#!/bin/sh

set -x

tailscaled &

sleep 10s
ps auxwwf

ip route del default
ip route add default via ${SUBNET_PREFIX}.3 dev eth0

if [ -n "$TAILSCALE_UP_LOGIN_SERVER" ]; then
	LOGIN_SERVER="--login-server $TAILSCALE_UP_LOGIN_SERVER"
	tailscale up --advertise-exit-node --login-server $TAILSCALE_UP_LOGIN_SERVER
else
	tailscale up --advertise-exit-node $LOGIN_SERVER
fi

apk add mtr curl

while [ 1 ]; do
	sleep 60
	date
done
