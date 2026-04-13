# tailscale-nordvpn
Create a dockerized Tailscale exit node with NordVPN's exit nodes.

This project creates two Docker containers: one for Tailscale and one for NordVPN. The Tailscale instance advertises itself as an exit node and routes all default traffic through the NordVPN container.

**Final intended operating mode: NordLynx / UDP**

## Architecture

```
client → tailscale container → nordvpn container → nordlynx → internet
```

The Tailscale container's default route is pointed at the NordVPN container. The NordVPN container masquerades outbound traffic through the active NordLynx (WireGuard) tunnel.

## Requirements
* A Docker host with Docker Compose.
* A NordVPN account and API token.

## Features
* Tailscale exit-node advertisement for outbound internet traffic.
* Optional pre-auth key for headless/automated Tailscale login.
* Support for a custom Tailscale login server.
* Connect to any NordVPN region.
* Automatic NordVPN reconnection on a configurable interval.
* Configurable `eth0` MTU for reliable performance through the double-tunnel stack.
* Persistent Tailscale state stored in a Docker named volume.

## Usage

1. Copy the example environment file:
   ```sh
   cp .env.example .env
   ```

2. Edit `.env` with your settings. Key variables:

   | Variable | Required | Description |
   |---|---|---|
   | `NORDVPN_TOKEN` | Yes | Your NordVPN access token. |
   | `NORDVPN_ENDPOINT` | Yes | NordVPN location (e.g. `San_Francisco`, `Japan`). |
   | `NORDVPN_TECHNOLOGY` | Yes | `NORDLYNX` (recommended) or `openvpn`. |
   | `NORDVPN_OPENVPN_PROTOCOL` | Yes | `udp` or `tcp` (only used with `openvpn`). |
   | `IP_SUBNET` | Yes | Docker bridge subnet. **Must be unique per instance** to avoid collisions with other Docker networks on the same host. |
   | `IP_TAILSCALE` | Yes | IP for the Tailscale container within the subnet. |
   | `IP_NORDVPN` | Yes | IP for the NordVPN container within the subnet. |
   | `TAILSCALE_AUTHKEY` | No | Pre-auth key for automated Tailscale login. Leave blank to log in manually. |
   | `TAILSCALE_ETH_MTU` | No | MTU for `eth0` in the Tailscale container. Default: `1385`. |
   | `TAILSCALE_UP_LOGIN_SERVER` | No | Custom Tailscale control server URL. |
   | `NORDVPN_RECONNECT_AFTER_HOURS` | No | Hours between automatic NordVPN server rotation. Default: `1`. |
   | `INSTANCE_NAME` | Yes | Short name used for container and compose-project naming. |

3. Start the stack:
   ```sh
   docker compose up -d
   ```

4. **Tailscale login**

   - If `TAILSCALE_AUTHKEY` is set, the container authenticates automatically.
   - If `TAILSCALE_AUTHKEY` is blank, watch the logs for the authentication URL:
     ```sh
     docker compose logs -f tailscale
     ```
     Open the printed URL in a browser to complete login.

## Persistence and Migration

Tailscale state is stored in the Docker named volume `tailscale-state`. This avoids accidentally committing the state file to Git while preserving login state across container restarts.

If you previously used the older bind-mount path at `./tailscale/state`, this repository does **not** migrate that state automatically. Before upgrading, either copy the existing state into the new Docker volume yourself or be prepared to authenticate Tailscale again after restarting the stack.

This repository no longer includes the experimental HTTP control panel for NordVPN. Management is performed through the `nordvpn` CLI inside the container, for example:

```sh
docker compose exec nordvpn nordvpn status
docker compose exec nordvpn nordvpn connect Japan
docker compose exec nordvpn nordvpn disconnect
```

## MTU Tuning

The Tailscale-over-NordLynx stack involves two tunnel layers. Without MTU adjustment, packets exceed the effective MTU and are silently dropped, causing connectivity issues.

The `TAILSCALE_ETH_MTU` variable sets the MTU on `eth0` inside the Tailscale container before `tailscaled` starts:

| MTU value | Result in testing |
|---|---|
| `1395+` | Unstable — packet loss under load |
| `1385` | **Current default** — stable and good throughput |
| `1380` | Stable |
| `1360` | Stable, slightly lower throughput |

`1385` is the current recommended value as a balance between stability and throughput.

## Validation

After the stack is running, verify with:

```sh
# Container status
docker compose ps

# NordVPN status (should report "NordLynx / UDP")
docker compose exec nordvpn nordvpn status

# Tailscale status
docker compose exec tailscale tailscale status
docker compose exec tailscale tailscale status --json
docker compose exec tailscale tailscale debug prefs
docker compose exec tailscale tailscale netcheck

# Confirm traffic exits through NordVPN public IP
docker compose exec tailscale wget -qO- https://ifconfig.me/ip

# Inside NordVPN container
docker compose exec nordvpn ip route
docker compose exec nordvpn ip rule
docker compose exec nordvpn iptables -t nat -L -n -v
```

This stack is validated for IPv4 egress through NordVPN. IPv6 forwarding is not configured or tested in the NordVPN container.

Expected results:
- `nordvpn status` reports `NordLynx / UDP`
- Tailscale default route points to `IP_NORDVPN` (e.g. `10.1.3.3`)
- `tailscale status --json` shows the node online
- Exit-route advertisement is enabled
- `tailscale netcheck` reports `UDP: true`
- `wget https://ifconfig.me/ip` returns the NordVPN exit IP

## Running Multiple Instances

Each instance must use a **unique `IP_SUBNET`**, `IP_TAILSCALE`, and `IP_NORDVPN` to avoid Docker network conflicts. For example:

```
# Instance 1
INSTANCE_NAME=jp_tokyo
IP_SUBNET=10.1.3.0/24
IP_TAILSCALE=10.1.3.2
IP_NORDVPN=10.1.3.3

# Instance 2
INSTANCE_NAME=us_sfo
IP_SUBNET=10.1.4.0/24
IP_TAILSCALE=10.1.4.2
IP_NORDVPN=10.1.4.3
```
