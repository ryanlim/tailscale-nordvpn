from flask import Flask, Blueprint, render_template, request, jsonify
from flask_cors import CORS
import concurrent.futures
import subprocess
import sys
import time
import logging
from pathlib import Path

import requests

# Pull in the shared NordVPN API/cache module that the `nordvpn` shim also
# uses. Single source of truth; one disk-backed cache for both consumers.
sys.path.insert(0, "/scripts")
import nordvpn_api  # noqa: E402

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- Public-IP lookup (cached) --------------------------------------------------

PUBLIC_IP_CACHE_TTL = 15  # seconds
PUBLIC_IP_TIMEOUT = 3     # seconds per upstream call

PUBLIC_IP_URLS = {
    "ipv4": "http://ip.limau.net/?format=json",
    "ipv6": "http://ip6.limau.net/?format=json",
}

_public_ip_cache: dict = {"data": None, "timestamp": 0.0}


def _fetch_public_ip(url: str) -> dict | None:
    """Call the limau.net IP service and return a flat dict, or None on error."""
    try:
        response = requests.get(url, timeout=PUBLIC_IP_TIMEOUT)
        response.raise_for_status()
        candidates = (response.json() or {}).get("ip_candidates") or []
    except (requests.RequestException, ValueError):
        return None
    if not candidates:
        return None
    candidate = candidates[0]
    geo = candidate.get("geoip_data") or {}
    asn_pair = candidate.get("ip_asn") or []
    return {
        "ip": candidate.get("ip"),
        "hostname": candidate.get("hostname"),
        "city": geo.get("city"),
        "region": geo.get("region"),
        "country_code": geo.get("country_code"),
        "asn": asn_pair[1] if len(asn_pair) > 1 else (asn_pair[0] if asn_pair else None),
    }


def get_public_ip() -> dict:
    """Return {"ipv4": {...}|None, "ipv6": {...}|None}, refreshing on TTL expiry."""
    now = time.monotonic()
    if (
        _public_ip_cache["data"] is not None
        and (now - _public_ip_cache["timestamp"]) < PUBLIC_IP_CACHE_TTL
    ):
        return _public_ip_cache["data"]

    keys = list(PUBLIC_IP_URLS.keys())
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(keys)) as pool:
        results = list(pool.map(_fetch_public_ip, [PUBLIC_IP_URLS[k] for k in keys]))
    data = dict(zip(keys, results))

    _public_ip_cache["data"] = data
    _public_ip_cache["timestamp"] = now
    return data


def _format_public_ip(info: dict) -> str:
    """Build a single-line summary like '1.2.3.4 (San Jose, US, AS7018)'."""
    parts = [p for p in (info.get("city"), info.get("country_code"), info.get("asn")) if p]
    suffix = f" ({', '.join(parts)})" if parts else ""
    return f"{info['ip']}{suffix}"


# --- Helpers --------------------------------------------------------------------

def run_nordvpn(*args: str) -> str:
    """Run a nordvpn sub-command and return combined stdout+stderr."""
    result = subprocess.run(
        ["nordvpn", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return (result.stdout + result.stderr).strip()


# --- API Blueprint (v1) ---------------------------------------------------------

api = Blueprint("api", __name__, url_prefix="/api/v1")
CORS(api)


@api.route("/openapi.json", methods=["GET"])
def openapi_spec():
    """Serve the OpenAPI 3.0 specification for this API."""
    base_url = request.url_root.rstrip("/") + "/api/v1"
    return jsonify({
        "openapi": "3.0.3",
        "info": {
            "title": "NordVPN Control API",
            "version": "1.0.0",
            "description": (
                "HTTP API for querying status and controlling a NordVPN connection.\n\n"
                "Server location codes use the format `{country_code}|{city_name}` "
                "(e.g. `us|new_york`). Retrieve the full list of valid codes from "
                "`GET /api/v1/servers`."
            ),
        },
        "servers": [{"url": base_url, "description": "NordVPN Control API"}],
        "tags": [
            {"name": "Servers", "description": "VPN endpoint discovery"},
            {"name": "Connection", "description": "VPN connection management"},
        ],
        "paths": {
            "/servers": {
                "get": {
                    "tags": ["Servers"],
                    "summary": "List available VPN server locations",
                    "description": (
                        "Returns the cached list of online NordVPN city endpoints, sorted "
                        "alphabetically. The cache is refreshed automatically every 6 hours "
                        "or on demand via `POST /api/v1/servers/refresh`."
                    ),
                    "operationId": "listServers",
                    "responses": {
                        "200": {
                            "description": "Sorted array of available city endpoints",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/City"},
                                    },
                                    "example": [
                                        {"name": "Germany - Berlin", "code": "de|berlin"},
                                        {"name": "United States - New York", "code": "us|new_york"},
                                    ],
                                }
                            },
                        },
                        "502": {
                            "description": "Failed to reach the NordVPN API",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Error"}
                                }
                            },
                        },
                    },
                }
            },
            "/servers/refresh": {
                "post": {
                    "tags": ["Servers"],
                    "summary": "Force-refresh the server list cache",
                    "description": "Invalidates the in-memory cache and fetches a fresh server list from the NordVPN API.",
                    "operationId": "refreshServers",
                    "responses": {
                        "200": {
                            "description": "Fresh sorted array of available city endpoints",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/City"},
                                    }
                                }
                            },
                        },
                        "502": {
                            "description": "Failed to reach the NordVPN API",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Error"}
                                }
                            },
                        },
                    },
                }
            },
            "/status": {
                "get": {
                    "tags": ["Connection"],
                    "summary": "Get current VPN connection status",
                    "operationId": "getStatus",
                    "responses": {
                        "200": {
                            "description": "Current VPN status",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/StatusResponse"},
                                    "examples": {
                                        "connected": {
                                            "summary": "Connected",
                                            "value": {
                                                "status": "Connected",
                                                "server": "us8765",
                                                "city_code": "us|new_york",
                                                "city": "United States - New York",
                                                "details": "Status: Connected\nHostname: us8765.nordvpn.com\n...",
                                            },
                                        },
                                        "disconnected": {
                                            "summary": "Disconnected",
                                            "value": {
                                                "status": "Disconnected",
                                                "server": None,
                                                "city_code": None,
                                                "city": None,
                                                "details": "Status: Disconnected",
                                            },
                                        },
                                    },
                                }
                            },
                        }
                    },
                }
            },
            "/connect": {
                "post": {
                    "tags": ["Connection"],
                    "summary": "Connect to a VPN server",
                    "description": (
                        "Connects to the NordVPN server in the specified city. "
                        "Use `GET /api/v1/servers` to obtain valid `server` codes."
                    ),
                    "operationId": "connect",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ConnectRequest"},
                                "example": {"server": "us|new_york"},
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Successfully connected",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/MessageResponse"},
                                    "example": {
                                        "message": "VPN connected!",
                                        "output": "You are connected to United States #8765 (us8765.nordvpn.com)!",
                                    },
                                }
                            },
                        },
                        "400": {
                            "description": "Invalid request or server not found",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Error"}
                                }
                            },
                        },
                    },
                }
            },
            "/disconnect": {
                "post": {
                    "tags": ["Connection"],
                    "summary": "Disconnect from VPN",
                    "operationId": "disconnect",
                    "responses": {
                        "200": {
                            "description": "Successfully disconnected (or was already disconnected)",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/MessageResponse"}
                                }
                            },
                        },
                        "400": {
                            "description": "Unexpected error from the nordvpn CLI",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Error"}
                                }
                            },
                        },
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "City": {
                    "type": "object",
                    "required": ["name", "code"],
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Human-readable location label (Country - City)",
                            "example": "United States - New York",
                        },
                        "code": {
                            "type": "string",
                            "description": "Machine-readable code for use with POST /connect",
                            "example": "us|new_york",
                        },
                    },
                },
                "StatusResponse": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["Connected", "Disconnected"],
                        },
                        "server": {
                            "type": "string",
                            "nullable": True,
                            "description": "Hostname prefix of the active server",
                            "example": "us8765",
                        },
                        "city_code": {
                            "type": "string",
                            "nullable": True,
                            "description": "Location code matching the format returned by GET /servers",
                            "example": "us|new_york",
                        },
                        "city": {
                            "type": "string",
                            "nullable": True,
                            "description": "Human-readable connected location",
                            "example": "United States - New York",
                        },
                        "details": {
                            "type": "string",
                            "description": "Raw output from `nordvpn status`",
                        },
                    },
                },
                "ConnectRequest": {
                    "type": "object",
                    "required": ["server"],
                    "properties": {
                        "server": {
                            "type": "string",
                            "description": "Location code from GET /servers (format: country_code|city_name)",
                            "example": "us|new_york",
                        }
                    },
                },
                "MessageResponse": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "example": "VPN connected!"},
                        "output": {
                            "type": "string",
                            "description": "Raw output from the nordvpn CLI",
                        },
                    },
                },
                "Error": {
                    "type": "object",
                    "properties": {
                        "error": {"type": "string", "example": "Failed to fetch server list"}
                    },
                },
            }
        },
    })


@api.route("/servers", methods=["GET"])
def get_servers():
    try:
        return jsonify(nordvpn_api.list_cities())
    except requests.RequestException as exc:
        logger.error("Failed to fetch server list: %s", exc)
        return jsonify({"error": "Failed to fetch server list"}), 502


@api.route("/servers/refresh", methods=["POST"])
def refresh_servers():
    nordvpn_api.refresh_cache("countries")
    try:
        return jsonify(nordvpn_api.list_cities())
    except requests.RequestException as exc:
        logger.error("Failed to refresh server list: %s", exc)
        return jsonify({"error": "Failed to fetch server list"}), 502


_WG_FIELD_LABELS = {
    "latest handshake": "Latest handshake",
    "transfer": "Transfer",
    "endpoint": "Endpoint",
}
_WG_FIELDS_TO_IGNORE = {
    "interface", "peer", "public key", "private key",
    "listening port", "fwmark", "allowed ips", "persistent keepalive",
}


def _parse_status(output: str) -> dict:
    """Parse `nordvpn status` output into a flat dict.

    Mixes two sources written to the same stdout: the shim's structured
    `Key: value` lines and the `wg show` dump (some indented, some not).
    Order isn't guaranteed, so parse without positional assumptions.
    """
    fields: dict = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key_raw, value = line.split(":", 1)
        key = key_raw.strip()
        value = value.strip()
        if not key:
            continue
        key_lower = key.lower()
        if key_lower in _WG_FIELD_LABELS:
            fields[_WG_FIELD_LABELS[key_lower]] = value
        elif key_lower in _WG_FIELDS_TO_IGNORE:
            continue
        else:
            fields[key] = value

    # `wg show` reports transfer as "X received, Y sent" — split for display.
    transfer = fields.pop("Transfer", None)
    if transfer:
        for piece in transfer.split(","):
            piece = piece.strip()
            if piece.endswith(" received"):
                fields["Received"] = piece[: -len(" received")].strip()
            elif piece.endswith(" sent"):
                fields["Sent"] = piece[: -len(" sent")].strip()
    return fields


def _add_public_ip_fields(fields: dict) -> None:
    public_ip = get_public_ip()
    for label, key in (("Public IPv4", "ipv4"), ("Public IPv6", "ipv6")):
        info = public_ip.get(key)
        if info and info.get("ip"):
            fields[label] = _format_public_ip(info)


@api.route("/status", methods=["GET"])
def vpn_status():
    if request.args.get("refresh"):
        _public_ip_cache["data"] = None
        _public_ip_cache["timestamp"] = 0.0

    status_output = run_nordvpn("status")

    if "Status: Connected" not in status_output:
        fields: dict = {}
        _add_public_ip_fields(fields)
        return jsonify({
            "status": "Disconnected",
            "details": status_output,
            "fields": fields,
            "server": None,
            "city_code": None,
            "city": None,
        })

    fields = _parse_status(status_output)
    _add_public_ip_fields(fields)

    hostname = fields.get("Hostname", "")
    connected_server_code = hostname.split(".")[0] if hostname else None
    connected_country_code = connected_server_code[:2] if connected_server_code else None
    connected_country = fields.get("Country")
    connected_city = fields.get("City")

    # Normalise to lowercase to match codes returned by GET /servers
    city_code = (
        f"{connected_country_code.lower()}|{connected_city.replace(' ', '_').lower()}"
        if connected_country_code and connected_city
        else None
    )

    return jsonify({
        "status": "Connected",
        "details": status_output,
        "fields": fields,
        "server": connected_server_code,
        "city_code": city_code,
        "city": (
            f"{connected_country} - {connected_city}"
            if connected_country and connected_city
            else None
        ),
    })


@api.route("/connect", methods=["POST"])
def connect_vpn():
    data = request.get_json(silent=True) or {}
    raw = data.get("server", "")
    parts = raw.split("|", 1)
    if len(parts) != 2 or not all(parts):
        return jsonify({"error": "Invalid server code. Expected format: 'xx|city_name'"}), 400

    country_code, city_name = parts
    logger.info("Connecting to %s / %s", country_code, city_name)
    result = run_nordvpn("connect", f"{country_code}|{city_name}")

    if "The specified server does not exist" in result:
        return jsonify({"error": "The specified server does not exist"}), 400
    if "You are connected to" in result:
        return jsonify({"message": "VPN connected!", "output": result}), 200
    return jsonify({"error": result}), 400


@api.route("/disconnect", methods=["POST"])
def disconnect_vpn():
    result = run_nordvpn("disconnect")

    if "You are not connected" in result:
        return jsonify({"message": "You are not connected.", "output": result}), 200
    if "You are disconnected" in result:
        return jsonify({"message": "VPN disconnected!", "output": result}), 200
    return jsonify({"error": result}), 400


app.register_blueprint(api)


# --- Web UI routes --------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/docs")
def api_docs():
    return render_template("api_docs.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
