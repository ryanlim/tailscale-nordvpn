"""VPN control-panel: serves the UI and proxies /api/v1/backends/<name>/* to
the configured VPN backend.

Backends are listed in a JSON config file (see backends.json.example). The
panel never knows backend specifics — it just forwards to whatever speaks the
v1 contract documented in BACKEND_API.md.
"""
import json
import logging
import os
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, render_template, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG_PATH = Path(os.environ.get("BACKENDS_CONFIG", "/config/backends.json"))
PROXY_TIMEOUT = 30  # seconds; status polls etc. should be well under this
# Hop-by-hop headers per RFC 7230 §6.1 — never forward these on either leg.
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}


def load_backends() -> list:
    """Read the backends list from disk on every call.

    Cheap (small JSON file) and lets operators edit the config without
    restarting the container.
    """
    if not CONFIG_PATH.exists():
        logger.warning("Backends config %s does not exist.", CONFIG_PATH)
        return []
    try:
        data = json.loads(CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to read %s: %s", CONFIG_PATH, exc)
        return []
    return data.get("backends", [])


def find_backend(name: str) -> dict | None:
    for b in load_backends():
        if b.get("name") == name:
            return b
    return None


# --- Routes -------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/v1/backends", methods=["GET"])
def list_backends():
    """Return the configured backends (panel-side metadata only).

    The frontend calls /api/v1/backends/<name>/info for the backend's
    self-reported type/instance.
    """
    backends = [
        {"name": b["name"], "label": b.get("label") or b["name"]}
        for b in load_backends()
        if b.get("name") and b.get("url")
    ]
    return jsonify({"backends": backends})


@app.route(
    "/api/v1/backends/<name>/<path:subpath>",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
def proxy(name: str, subpath: str):
    backend = find_backend(name)
    if backend is None:
        return jsonify({"error": f"Unknown backend: {name}"}), 404

    upstream_url = backend["url"].rstrip("/") + "/api/v1/" + subpath
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP and k.lower() != "host"
    }

    try:
        upstream = requests.request(
            method=request.method,
            url=upstream_url,
            params=request.args,
            headers=headers,
            data=request.get_data(),
            timeout=PROXY_TIMEOUT,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        logger.warning("Proxy to %s failed: %s", upstream_url, exc)
        return jsonify({"error": f"Backend '{name}' unreachable: {exc}"}), 502

    response_headers = [
        (k, v) for k, v in upstream.headers.items()
        if k.lower() not in HOP_BY_HOP
    ]
    return Response(upstream.content, status=upstream.status_code, headers=response_headers)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
