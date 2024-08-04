# tailscale-nordvpn
Create a dockerized Tailscale exit node with NordVPN's exit nodes.

This project will create two docker containers. One for Tailscale, and another for NordVPN. The Tailscale instance will advertise as an exit node, and use the NordVPN container as an egress route.

## Requirements
* A docker host, and docker build tools.
* NordVPN account.

## Features
* Support for using an alternate login-server.
* Connect to any NordVPN region.

## Usage
1. Copy the `.env.example` to `.env`.
2. Customize your .env file with the desired settings:
    * `NORDVPN_TOKEN`: Your NordVPN login token.
    * `TAILSCALE_UP_LOGIN_SERVER`: Your custom Tailscale login server.
    * `NORDVPN_ENDPOINT`: a NordVPN location (the same argument as `nordvpn connect ...`)
    * `NORDVPN_TECHNOLOGY`: `OPENVPN` or `NORDLYNX`
    * `NORDVPN_OPENVPN_PROTOCOL`: `TCP` or `UDP`
3. Run `docker compose up -d`. You will have to watch the logs of the tailscale container for next steps. If you need to get a shell into the container, run:
     `docker compose exec -it tailscale /bin/sh`
