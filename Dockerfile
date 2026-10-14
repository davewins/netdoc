# syntax=docker/dockerfile:1
# --- frontend build (never shipped)
FROM node:22-slim AS frontend-build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
# vite.config.ts writes to ../backend/static relative to this dir, i.e. /src/backend/static
RUN npm run build

# --- backend build: pip deps + nmap, using Chainguard's -dev image (has apk/pip/shell).
# The runtime stage below has no shell, pip or apk, so everything is staged here.
FROM cgr.dev/chainguard/python:latest-dev AS build
USER root
WORKDIR /build
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir --no-compile --target /deps -r requirements.txt
# nmap powers the network-scan connector. Chainguard's build carries file
# capabilities (cap_net_raw/admin/bind_service=eip) so it can run as non-root
# when the container is granted NET_RAW/NET_ADMIN; copied with them in tact via
# the tar below (COPY --from drops xattrs).
RUN apk add --no-cache nmap \
    && mkdir -p /stage/usr/bin /stage/usr/lib /stage/usr/share \
    && cp -a /usr/share/nmap /stage/usr/share/nmap \
    && cp -a /usr/lib/libssl.so.3 /usr/lib/libcrypto.so.3 /stage/usr/lib/ \
    && cp /usr/bin/nmap /stage/usr/bin/nmap
COPY backend/app /app/app
COPY --from=frontend-build /src/backend/static /app/static
RUN mkdir -p /data

# --- runtime: Chainguard Python (distroless: no shell/apk, patched continuously), uid 65532
FROM cgr.dev/chainguard/python:latest
COPY --from=build /deps /deps
COPY --from=build /app /app
COPY --from=build /stage/usr/ /usr/
COPY --from=build --chown=65532:65532 /data /data
ENV PYTHONPATH=/deps:/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NETDOC_DATA_DIR=/data \
    NETDOC_PORT=8000
WORKDIR /app
EXPOSE 8000
VOLUME ["/data"]
USER 65532:65532
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
  CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('NETDOC_PORT','8000'), timeout=4)"]
# Exec form (no shell to expand ${NETDOC_PORT}), so app.__main__-style launch reads the env itself.
ENTRYPOINT ["python", "-c", "import os,uvicorn; uvicorn.run('app.main:app', host='0.0.0.0', port=int(os.environ.get('NETDOC_PORT','8000')))"]
