FROM ubuntu:24.04

RUN apt update && \
    apt install -y --no-install-recommends \
        apt-transport-https \
        ca-certificates \
        iputils-ping \
        less \
        mtr \
        traceroute \
        wget && \
    wget -qO /etc/apt/trusted.gpg.d/nordvpn_public.asc https://repo.nordvpn.com/gpg/nordvpn_public.asc && \
    echo "deb https://repo.nordvpn.com/deb/nordvpn/debian stable main" > /etc/apt/sources.list.d/nordvpn.list && \
    apt update && \
    apt install -y --no-install-recommends nordvpn && \
    apt clean && \
    rm -rf /var/lib/apt/lists/*

CMD ["bash"]
