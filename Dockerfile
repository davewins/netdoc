FROM node:20-slim AS frontend-build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
# vite.config.ts writes to ../backend/static relative to this dir, i.e. /src/backend/static
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

# nmap powers the network-scan connector's ARP/ping/port discovery.
RUN apt-get update && apt-get install -y --no-install-recommends nmap \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend-build /src/backend/static ./static

ENV NETDOC_DATA_DIR=/data
ENV NETDOC_PORT=8000
VOLUME ["/data"]
EXPOSE 8000

# Shell form so ${NETDOC_PORT} expands - lets a host where 8000 is already
# taken (common with network_mode: host, since it's binding to the host's
# real port space, not an isolated bridge network) override it without
# touching this file.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${NETDOC_PORT}
