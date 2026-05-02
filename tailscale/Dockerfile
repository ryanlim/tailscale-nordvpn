FROM tailscale/tailscale:latest

# Pre-install the auxiliary tools the entrypoint relies on (tinyproxy for
# the reverse proxy to the control panel, curl for the watchdog probes,
# mtr for diagnostics, node_exporter for metrics). Doing this at build time
# avoids a flaky apk fetch on every container start, which previously
# wedged tinyproxy when downloads stalled through the VPN tunnel.
RUN apk add --no-cache \
    mtr \
    curl \
    prometheus-node-exporter \
    tinyproxy
