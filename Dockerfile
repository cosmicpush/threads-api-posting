# --- Stage 1: fetch supercronic for the target architecture ---
FROM alpine:3.20 AS supercronic
ARG SUPERCRONIC_VERSION=0.2.30
ARG TARGETARCH
RUN apk add --no-cache wget ca-certificates \
    && wget -q -O /supercronic \
        "https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH}" \
    && chmod +x /supercronic

# --- Stage 2: runtime image ---
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# tzdata so the TZ env var actually resolves to a zoneinfo entry
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=supercronic /supercronic /usr/local/bin/supercronic
COPY threads_poster ./threads_poster
COPY crontab /app/crontab

RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 poster \
    && mkdir -p /data /var/lock/threads_poster \
    && chown -R poster:poster /app /data /var/lock/threads_poster

USER poster

ENV QUOTES_JSON_PATH=/data/quotes.json \
    LOCKFILE_PATH=/var/lock/threads_poster/threads_poster.lock

# supercronic stays in the foreground and logs to stdout — perfect for Docker.
CMD ["supercronic", "/app/crontab"]
