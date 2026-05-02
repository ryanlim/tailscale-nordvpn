# VPN Backend API Contract (v1)

Every VPN backend container (currently `nordvpn`, `nordvpn-wg`; future:
ProtonVPN, Mullvad, …) MUST implement this HTTP API. The control-panel
container is backend-agnostic and only speaks to backends through these
endpoints.

- Base path: `/api/v1`
- Content type: `application/json`
- Backends are reachable on the internal docker network, no auth required.
- Backends are addressed by panel-side **name** (set in `BACKENDS=`
  config). The backend itself reports its **type** and **instance** via
  `/info`; everything else in the contract is identical across backends.

## Endpoints

### `GET /api/v1/info`

Backend identity. Used by the panel to label backends and disambiguate
multiple instances of the same type.

```json
{
  "backend_type": "nordvpn-wg",
  "instance": "us-1",
  "version": "1"
}
```

- `backend_type` — slug identifying the implementation
  (`nordvpn`, `nordvpn-wg`, `protonvpn`, …).
- `instance` — opaque per-container label (typically `INSTANCE_NAME`
  from compose). Stable across restarts.
- `version` — contract version this backend implements.

### `GET /api/v1/status`

Current connection state. Always 200 OK.

```json
{
  "status": "Connected" | "Disconnected",
  "server": "us8765" | null,
  "city_code": "us|new_york" | null,
  "city": "United States - New York" | null,
  "fields": {
    "Country": "United States",
    "City": "New York",
    "Hostname": "us8765.nordvpn.com",
    "Endpoint": "1.2.3.4:51820",
    "Load": "27",
    "Technology": "WireGuard (NordLynx)",
    "Uptime": "0h 4m 35s",
    "Latest handshake": "1 minute, 23 seconds ago",
    "Received": "12.3 MiB",
    "Sent": "456 KiB",
    "Public IPv4": "1.2.3.4 (San Jose, US, AS7018)",
    "Public IPv6": "..."
  },
  "details": "raw output from the underlying VPN CLI"
}
```

- `fields` is the canonical render-this-as-a-table dict. Backends
  populate whichever keys make sense; the panel renders a fixed set in
  display order and silently skips missing keys.
- `Public IPv4` / `Public IPv6` MAY appear in `fields` even when
  `status` is `Disconnected` — useful for confirming the host's real
  IP is exposed (i.e. tunnel is genuinely down).
- Query: `?refresh=1` invalidates the backend's public-IP cache before
  responding.

### `POST /api/v1/connect`

```json
// Request
{ "server": "us|new_york" }
```

- `server` is a `country_code|city_name` token from `GET /servers`.
  `country_code` is lowercase ISO-3166-alpha-2; `city_name` is
  lowercase, spaces replaced with `_`.
- 200 OK on success: `{ "message": "VPN connected!", "output": "..." }`.
- 400 on resolver/connect failure: `{ "error": "..." }`.

### `POST /api/v1/disconnect`

No request body.

- 200 OK: `{ "message": "...", "output": "..." }` whether already
  disconnected or just disconnected.
- 400 on unexpected error: `{ "error": "..." }`.

### `GET /api/v1/servers`

```json
[
  { "code": "de|berlin",   "name": "Germany - Berlin" },
  { "code": "us|new_york", "name": "United States - New York" }
]
```

Sorted by `name`. Backed by a per-backend cache (typical TTL 24h).

### `POST /api/v1/servers/refresh`

Invalidates the backend's server-list cache and returns the same shape
as `GET /servers`.

### `GET /api/v1/public-ip`

```json
{
  "ipv4": {
    "ip": "1.2.3.4",
    "hostname": "...",
    "city": "San Jose",
    "region": "California",
    "country_code": "US",
    "asn": "AT&T Enterprises, LLC"
  } | null,
  "ipv6": { ...same shape... } | null
}
```

Looked up from inside the backend container (so the response reflects
the IP the backend's tunnel is exiting through). MAY be cached briefly
(typical TTL 15s); `?refresh=1` forces a fresh upstream lookup.

## Error shape

Every non-2xx response uses:

```json
{ "error": "human-readable message" }
```

## Versioning

The base path includes `v1`. Breaking changes bump to `v2` and the
panel SHOULD be able to talk to mixed-version backends during
rollouts.
