FROM ubuntu:24.04

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates \
      python3-requests \
      python3-flask \
      python3-flask-cors && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY app.py /app/app.py
COPY templates/ /app/templates/
COPY config/ /app/config/

ENV BACKENDS_CONFIG=/config/backends.json

EXPOSE 80
CMD ["python3", "/app/app.py"]
