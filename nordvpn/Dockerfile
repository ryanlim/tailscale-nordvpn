FROM ubuntu:24.04

RUN apt-get update && \
    apt-get install -y --no-install-recommends wget curl apt-transport-https ca-certificates && \ 
    wget -qO /etc/apt/trusted.gpg.d/nordvpn_public.asc https://repo.nordvpn.com/gpg/nordvpn_public.asc && \
    echo "deb https://repo.nordvpn.com/deb/nordvpn/debian stable main" > /etc/apt/sources.list.d/nordvpn.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nordvpn && \
    apt-get install -y --no-install-recommends mtr iputils-ping traceroute less  && \
    apt-get install -y --no-install-recommends python3-requests python3-flask && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY NordVPN-WebInterface /webapp

ENTRYPOINT /etc/init.d/nordvpn start && sleep 5 && /bin/bash -c "$@"
CMD bash
