from flask import Flask, Blueprint, render_template, request, jsonify
from flask_cors import CORS
import subprocess
import time
import logging
import requests

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Server list cache -----------------------------------------------------------

CACHE_TTL = 6 * 3600  # seconds; adjust as needed

_server_cache: dict = {"data": None, "timestamp": 0.0}


def _fetch_servers() -> list:
    """Fetch the NordVPN server list and return sorted city entries."""
    response = requests.get(
        "https://api.nordvpn.com/v1/servers?limit=0", timeout=30
    )
    response.raise_for_status()
    servers = response.json()

    seen_cities: set = set()
    city_list: list = []

    for server in servers:
        if server.get("status") != "online":
            continue

        locations = server.get("locations")
        if not locations:
            continue

        country = locations[0].get("country", {})
        country_code = country.get("code")
        country_name = country.get("name")
        city = country.get("city") or {}
        city_name = city.get("name")

        if not country_code or not city_name:
            continue

        # Normalise to lowercase so codes are consistent across /servers and /status
        city_key = f"{country_code.lower()}|{city_name.replace(' ', '_').lower()}"
        if city_key not in seen_cities:
            seen_cities.add(city_key)
            city_list.append({"name": f"{country_name} - {city_name}", "code": city_key})

    return sorted(city_list, key=lambda d: d["name"])


def get_cached_servers() -> list:
    """Return the server list from cache, refreshing it if the TTL has expired."""
    now = time.monotonic()
    if _server_cache["data"] is None or (now - _server_cache["timestamp"]) > CACHE_TTL:
        logger.info("Refreshing NordVPN server list cache…")
        _server_cache["data"] = _fetch_servers()
        _server_cache["timestamp"] = now
        logger.info("Server list cached (%d cities).", len(_server_cache["data"]))
    return _server_cache["data"]


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
        return jsonify(get_cached_servers())
    except requests.RequestException as exc:
        logger.error("Failed to fetch server list: %s", exc)
        return jsonify({"error": "Failed to fetch server list"}), 502


@api.route("/servers/refresh", methods=["POST"])
def refresh_servers():
    _server_cache["data"] = None
    try:
        return jsonify(get_cached_servers())
    except requests.RequestException as exc:
        logger.error("Failed to refresh server list: %s", exc)
        return jsonify({"error": "Failed to fetch server list"}), 502


@api.route("/status", methods=["GET"])
def vpn_status():
    status_output = run_nordvpn("status")

    if "Status: Connected" not in status_output:
        return jsonify({
            "status": "Disconnected",
            "details": status_output,
            "server": None,
            "city_code": None,
            "city": None,
        })

    connected_server_code = None
    connected_country_code = None
    connected_country = None
    connected_city = None

    for line in status_output.splitlines():
        if "Hostname" in line:
            connected_server_code = line.split(":", 1)[1].strip().split(".")[0]
            connected_country_code = connected_server_code[:2]
        elif "Country" in line:
            connected_country = line.split(": ", 1)[1]
        elif "City" in line:
            connected_city = line.split(": ", 1)[1]

    # Normalise to lowercase to match codes returned by GET /servers
    city_code = (
        f"{connected_country_code.lower()}|{connected_city.replace(' ', '_').lower()}"
        if connected_country_code and connected_city
        else None
    )

    return jsonify({
        "status": "Connected",
        "details": status_output,
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
    result = run_nordvpn("connect", country_code, city_name)

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
