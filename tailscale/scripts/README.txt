This directory is bind-mounted into the tailscale container at /scripts/.

Drop ad-hoc helper scripts here and they'll be available inside the
container without rebuilding the image. Anything in this directory other
than this README is gitignored — it's intended for local-only tooling
(cert distribution, one-off probes, etc.).

The container's main entrypoint (tailscale_up.sh) is baked into the
image at /tailscale_up.sh; edit it under tailscale/ and rebuild with
`docker compose build tailscale` to roll changes.
