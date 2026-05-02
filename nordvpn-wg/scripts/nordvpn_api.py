"""Shared NordVPN API + cache helpers for the CLI shim and the web app.

The on-disk cache lives at /etc/wireguard/.cache.json and is keyed per fetch
("countries", "groups", ...). Anything that wants fresh data should call
refresh_cache() (or refresh_cache(key)) first.
"""
import json
import time
from pathlib import Path

import requests

CACHE_FILE = Path("/etc/wireguard/.cache.json")
CACHE_TTL = 24 * 3600
API_BASE = "https://api.nordvpn.com/v1"


def api_get(path, params=None):
    r = requests.get(f"{API_BASE}/{path}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def _load_cache():
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache):
    try:
        CACHE_FILE.write_text(json.dumps(cache))
    except OSError:
        pass


def cached(key, fetch):
    cache = _load_cache()
    entry = cache.get(key)
    if entry and time.time() - entry.get("fetched_at", 0) < CACHE_TTL:
        return entry["data"]
    try:
        data = fetch()
    except requests.RequestException:
        if entry:
            return entry["data"]
        raise
    cache[key] = {"fetched_at": time.time(), "data": data}
    _save_cache(cache)
    return data


def refresh_cache(key=None):
    """Drop one cache entry, or the whole cache if no key is given."""
    cache = _load_cache()
    if key is None:
        cache = {}
    else:
        cache.pop(key, None)
    _save_cache(cache)


def list_countries():
    return cached("countries", lambda: api_get("servers/countries"))


def list_groups():
    return cached("groups", lambda: api_get("servers/groups"))


def list_cities():
    """Flatten the country catalog into city entries the web UI can render.

    Returns a list of {"code": "xx|city_name", "name": "Country - City"},
    sorted by display name. Cities the API doesn't expose a code/name for are
    silently skipped.
    """
    cities = []
    for country in list_countries():
        country_name = country.get("name")
        country_code = (country.get("code") or "").lower()
        if not country_name or not country_code:
            continue
        for city in country.get("cities", []):
            city_name = city.get("name")
            if not city_name:
                continue
            code = f"{country_code}|{city_name.replace(' ', '_').lower()}"
            cities.append({"code": code, "name": f"{country_name} - {city_name}"})
    cities.sort(key=lambda d: d["name"])
    return cities
