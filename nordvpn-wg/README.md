# nordvpn-wg

A drop-in replacement for the `nordvpn` service in this repo that uses plain
WireGuard instead of the NordVPN CLI. Smaller image, no daemon, faster
reconnects, and a `nordvpn` command that mimics the official CLI for connecting
to specific countries / cities / groups / servers.

## How it works

NordVPN's "NordLynx" protocol is WireGuard with a per-account private key. Once
you have that key, you can talk to any NordVPN WireGuard server directly using
stock `wg-quick` — no NordVPN client needed at runtime. This service:

1. Reads your private key from `./wireguard/private.key` (a bind-mounted volume).
2. On startup, asks NordVPN's public API for a recommended WireGuard server
   matching your target (country / city / group / hostname / auto).
3. Generates `wg0.conf`, brings up `wg0` with `wg-quick`, applies the same
   iptables MASQUERADE/FORWARD rules the old service used.
4. Sleeps `RECONNECT_AFTER_HOURS`, tears down, and reconnects to a fresh
   recommended server matching the same target. The target persists across
   container restarts via `/etc/wireguard/.target`.

## One-time setup

### 1. Fetch your WireGuard private key

```sh
./nordvpn-wg/scripts/extract_key.sh > ./nordvpn-wg/wireguard/private.key
chmod 600 ./nordvpn-wg/wireguard/private.key
```

The script reads `NORDVPN_TOKEN` from your project-root `.env` and calls
`https://api.nordvpn.com/v1/users/services/credentials`. The key it returns is
reusable across every NordVPN WireGuard server, and only needs to be fetched
again if you rotate your NordVPN access token.

### 2. Swap the service in docker-compose.yml

Comment out the existing `nordvpn:` service and uncomment the `nordvpn-wg:`
block. They share `container_name` and `IP_NORDVPN`, so only one runs at a time
— the tailscale container's routing keeps working unchanged.

### 3. Build and start

```sh
docker compose up -d --build nordvpn-wg
docker logs -f tailnord-nordvpn-${INSTANCE_NAME}
```

You should see "Selected: usNNNN.nordvpn.com (...)" then "Connected."

## CLI usage

The `nordvpn` command inside the container mimics the official CLI surface.
Run it via `docker exec`:

```sh
docker exec -it tailnord-nordvpn-${INSTANCE_NAME} nordvpn <subcommand>
```

### Connecting

```sh
nordvpn connect                  # NordVPN-recommended server, anywhere
nordvpn connect United_States    # by country
nordvpn connect Tokyo            # by city
nordvpn connect P2P              # by group title
nordvpn connect legacy_p2p       # by group identifier
nordvpn connect us9677           # by specific server hostname
```

Underscores in country/city names are treated as spaces, matching the official
CLI (`Los_Angeles` → `Los Angeles`). The chosen target is saved to
`/etc/wireguard/.target` so periodic reconnects keep using it (picking a fresh
recommended server within that scope each time).

### Inspecting

```sh
nordvpn status      # current server, country, city, uptime, wg transfer stats
nordvpn countries   # list all countries (one per line, underscored)
nordvpn cities United_States
nordvpn groups      # list group identifiers + titles
nordvpn servers Tokyo --limit 10   # peek at top-N recommendations
```

### Disconnecting

```sh
nordvpn disconnect
```

The container's reconnect loop will reconnect on its next iteration. To stop
permanently, `docker compose stop nordvpn-wg`.

## Configuration

Set in `.env`:

| Variable                       | Purpose                                                  |
| ------------------------------ | -------------------------------------------------------- |
| `NORDVPN_TOKEN`                | Used once, by `extract_key.sh`. Not needed at runtime.   |
| `NORDVPN_ENDPOINT`             | Default target on first start (e.g. `Los_Angeles`).      |
| `NORDVPN_RECONNECT_AFTER_HOURS`| How long to hold each tunnel before rotating servers.    |
| `IP_NORDVPN` / `IP_SUBNET`     | Same as the original nordvpn service.                    |

The compose service maps `NORDVPN_ENDPOINT` to `NORDVPN_TARGET` for the
container; once a target is set via `nordvpn connect`, the persisted
`.target` file overrides the env var.

## Files

```
nordvpn-wg/
├── Dockerfile               # ubuntu:24.04 + wireguard-tools + iptables + python3-requests
├── scripts/
│   ├── entrypoint.sh        # connect + reconnect loop
│   ├── nordvpn              # CLI wrapper (Python)
│   ├── iptables_rules.sh    # MASQUERADE + FORWARD rules for wg0
│   └── extract_key.sh       # one-shot API fetch for the WireGuard private key
└── wireguard/
    ├── .gitignore           # ignores private.key, wg0.conf, .target, .cache.json
    ├── private.key          # YOU CREATE THIS (step 1 above)
    ├── wg0.conf             # generated on every connect
    ├── .target              # last target (persists across restarts)
    └── .cache.json          # cached countries/groups (24h TTL, see below)
```

## Caching

The country and group lists from NordVPN's API are cached in
`./wireguard/.cache.json` for 24 hours so name resolution and
`nordvpn countries` / `cities` / `groups` are instant after the first call.
Server *recommendations* are never cached — those are load-balanced and need
to be fresh every reconnect.

If the API is unreachable, stale cache entries are served instead of failing.
To force a refresh, delete the cache file:

```sh
docker exec tailnord-nordvpn-${INSTANCE_NAME} rm /etc/wireguard/.cache.json
```

## Troubleshooting

**Container restarts in a loop with "PRIVATE_KEY_FILE missing"**
You skipped step 1. Run `extract_key.sh`.

**`nordvpn connect` says "Could not resolve 'X'"**
The name didn't match a country/city/group/server. Try `nordvpn countries`
or `nordvpn cities <country>` to see the exact spelling. Use underscores
instead of spaces.

**Tunnel comes up but no traffic flows**
Check `iptables -t nat -L POSTROUTING -n -v` inside the container — the
MASQUERADE rule on `wg0` should be present. Check the tailscale container is
still using `IP_NORDVPN` as its egress.

**Want to rotate to a new server immediately**
`nordvpn connect` (with the same or a new target) — it tears down the current
tunnel and brings up a new one without waiting for the reconnect timer.

**IPv6**
NordVPN doesn't offer IPv6 to clients, so the service keeps
`net.ipv6.conf.all.disable_ipv6=1` to prevent leaks around the tunnel.

## Differences from the official NordVPN CLI

What's gone:
- `nordvpn login` / `nordvpn logout` (auth happens once via `extract_key.sh`)
- `nordvpn set killswitch on` (enforced via iptables; the tunnel-down state
  blocks forwarded traffic because the FORWARD rules reference `wg0`)
- `nordvpn set cybersec` / `obfuscate` / `notify` (no equivalent — these are
  client-side features, not WireGuard-level)
- `nordvpn allowlist` (use iptables directly if needed)
- OpenVPN protocol (WireGuard only)

What's the same shape:
- `connect`, `disconnect`, `status`, `countries`, `cities`, `groups`
- Underscore-as-space target syntax
- Persistent reconnect-on-restart behavior
