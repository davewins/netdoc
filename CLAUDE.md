# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

netdoc is a self-hosted network inventory tool for a homelab: it polls Proxmox, Portainer and Pi-hole APIs plus an active nmap LAN scan to discover what's running, cross-references records from different sources into one entry per real host, and gives a web UI to enrich each one with what no API exposes (ports, credentials, notes, service labels). See `README.md` for the full feature/setup rundown - this file is about how the code fits together, not what it does for the user.

**There is no test suite.** Verification so far has been manual: run the backend, exercise the API with curl, run the frontend build, click through the UI. Bear that in mind when changing connector parsing or the correlation logic - those were bugs found this way (see "Known-subtle areas" below), not caught by any automated check.

## Commands

```bash
# backend - from backend/
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
NETDOC_DATA_DIR=./data uvicorn app.main:app --reload --port 8123

# frontend - from frontend/, in another shell
npm install
npm run dev              # http://localhost:5173, proxies /api to :8123
npm run build             # tsc -b && vite build; writes into ../backend/static

# full container build/run
docker compose build
docker compose up -d
```

`docker-compose.yml` pins `name: netdoc` at the top level, so every clone of this repo (regardless of the directory it's checked out into, or which OS user runs it) resolves to the same `netdoc` container and `netdoc_netdoc-data` volume. Don't remove that pin - a differently-named checkout directory would otherwise spin up a second, disconnected instance instead of managing the one already running.

## Current deployment

A live instance is already running on this machine (container name `netdoc`, `docker compose ps` to check) with three real connectors configured (Proxmox, Portainer, Pi-hole) and hundreds of discovered assets, encrypted credentials, and pending link suggestions in the `netdoc_netdoc-data` volume. Don't re-add connectors or treat this as a fresh scaffold - `docker compose build && docker compose up -d` from a checkout rebuilds the image and redeploys against that same existing data. The listen port is set via a gitignored `.env` file (`NETDOC_PORT=...`) next to `docker-compose.yml`, not committed, since it's host-specific (port 8000 was already taken by something else here).

## Architecture

**Backend**: FastAPI + SQLAlchemy + SQLite, single process. `main.py` wires everything: runs `migrations.run_additive_migrations()` then `Base.metadata.create_all()` on startup, mounts the API routers, starts the APScheduler background poller, and serves the built frontend with an SPA-fallback catch-all route.

**Data model** (`models.py`) is deliberately one polymorphic `Asset` table rather than per-type tables (`vm`, `docker_container`, etc. are just values of `asset_type`) - discovery, enrichment, and cross-source linking all need to treat every kind of thing uniformly, so a shared shape wins over normalization here. Enrichment fields (`notes`, `tags`, `ports`, `services`) are JSON columns. `Connector` holds per-source config with credentials encrypted as a single JSON blob; `Credential` rows (manually-added, per-asset) are encrypted individually. `AssetLink` records a same-host relationship between two assets discovered from different sources.

**Connectors** (`connectors/`): each is a `BaseConnector` subclass implementing one `poll() -> list[DiscoveredAsset]`. `DiscoveredAsset` is a flat dataclass - parent/child relationships are expressed via `parent_external_id` (matched against another asset's `external_id` from the same connector), not nested structures. Adding a new source is: write one connector file, register it in `connectors/__init__.py`'s `CONNECTOR_TYPES`, done - the scheduler/upsert/correlation code needs no changes. `DiscoveredAsset.initial_tags/initial_services/initial_ports` are only applied the first time an asset is created (see `scheduler.poll_connector`) so a re-poll never clobbers what a user typed into the enrichment UI; `cpu_cores/memory_mb/disk_gb/uptime_seconds` *do* get overwritten on every poll since those are meant to track the live source, not user input.

The `network_scan` connector reuses the `Connector.base_url` field as a CIDR range rather than a URL (no server to talk to, and adding a dedicated column for one connector type wasn't worth it) - see the docstring in `connectors/network_scan.py`. It shells out to `nmap` and needs the container to run with `network_mode: host` + `NET_ADMIN`/`NET_RAW` to see real LAN devices; this only works on a Linux Docker host; Docker Desktop (Mac/Windows) can't give a container real host network access, so on those platforms the app runs fine but this connector finds nothing.

**Scheduler → correlation pipeline** (`scheduler.py`, `correlation.py`): `poll_connector()` upserts one connector's discovered assets, then always calls `correlation.run_correlation()` before returning - both `poll_all()` (the periodic job) and the "poll now" endpoint go through this same path, so correlation is never something a caller has to remember to trigger separately. Correlation logic: assets sharing a normalized MAC address are auto-merged (`canonical_asset_id` set on the losing side, priority ranked by `TYPE_PRIORITY` - VM/LXC beats a passively-observed DNS/DHCP/scan hit); assets sharing only an IP produce a `pending` `AssetLink` for the user to confirm/reject via `/api/links`, never an automatic merge, since DHCP reassigns IPs.

**Encryption** (`crypto.py`): Fernet key generated on first run and persisted at `/data/master.key` inside the data volume (or set explicitly via `NETDOC_MASTER_KEY`). Losing that file makes every stored credential unrecoverable - there is no recovery path, by design.

**Migrations** (`migrations.py`): additive-only `ALTER TABLE ADD COLUMN` for the `assets` table, applied before `create_all()`. This is intentionally not a real migration framework (single-user SQLite app) - it only knows how to add nullable columns. A schema change that needs anything else (renaming/dropping a column, a new constraint) needs a different, manual approach.

**Frontend**: React + TypeScript + Vite, no state management library - each page fetches what it needs directly through `api.ts`. `vite.config.ts` builds assets into `app-assets/`, *not* the Vite default `assets/` - that default would collide with the app's own `/assets/:id` route (asset detail pages) once `main.py`'s SPA-fallback mounts a static-file handler at the same path. If you ever see 404s on direct navigation to a client-side route, check that mount/build-output pairing first.

## Known-subtle areas (bugs already found and fixed here - don't reintroduce)

- **Docker bridge IPs must not participate in IP-based correlation.** Every docker-compose stack gets its own isolated `172.16.0.0/12` subnet, so "first container in its network" IPs like `172.19.0.2` collide constantly across totally unrelated containers. `correlation._is_correlatable_ip()` excludes that range (plus loopback/link-local) from the IP-grouping pass. This was found by running against real production data - it looked fine with small test fixtures.
- **The IP-suggestion "hub" must be stable across correlation runs**, not recomputed by priority every time. If it were, discovering a higher-priority asset later (e.g. Portainer finding a container after Pi-hole already linked its DNS records) would pick a new hub and fan out a *second* set of suggestions instead of extending the first, producing duplicate-looking pairs. `run_correlation()` checks for an existing link within the candidate group and reuses its primary as the hub before falling back to a fresh priority-based pick.
- **On a MAC-based merge, backfill the canonical asset's `ip_address`/`hostname`** from the record being merged in, when the canonical one doesn't already have its own. Without this a Proxmox VM (which usually has no IP without a guest agent) stays blank in Inventory even after merging in a DHCP reservation that has the IP right there.
