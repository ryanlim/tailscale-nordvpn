#!/bin/bash
# Fetch the NordVPN WireGuard (NordLynx) private key from the NordVPN API.
#
# Usage:
#   ./extract_key.sh > ../wireguard/private.key
#
# Reads NORDVPN_TOKEN from the environment, or from the project-root .env file
# if not set. The token is your standard NordVPN access token (the same value
# already used by the existing nordvpn service). The returned key is reusable
# across every NordVPN WireGuard server.

set -e

if [ -z "$NORDVPN_TOKEN" ]; then
  ENV_FILE="$(cd "$(dirname "$0")/../.." && pwd)/.env"
  if [ -f "$ENV_FILE" ]; then
    NORDVPN_TOKEN=$(grep -E '^NORDVPN_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
  fi
fi

if [ -z "$NORDVPN_TOKEN" ]; then
  echo "NORDVPN_TOKEN is unset and not found in .env." >&2
  exit 1
fi

RESPONSE=$(curl -fsS -u "token:$NORDVPN_TOKEN" \
  https://api.nordvpn.com/v1/users/services/credentials)

KEY=$(printf '%s' "$RESPONSE" | python3 -c \
  'import sys,json; print(json.load(sys.stdin)["nordlynx_private_key"])')

if [ -z "$KEY" ] || [ "${#KEY}" -lt 40 ]; then
  echo "Unexpected API response: $RESPONSE" >&2
  exit 1
fi

echo "$KEY"
