# netdoc

A self-hosted network inventory tool: it polls Proxmox, Portainer and
Pi-hole to automatically discover what's running on your network, and
gives you a web UI to enrich each discovered thing with the details no
API exposes - ports, credentials, notes, "what service is this actually
running" tags.

v1 is read-only against your infrastructure: it only ever calls list/read
API endpoints, never changes anything on Proxmox/Portainer/Pi-hole.

## What it discovers

- **Proxmox VE**: nodes, VMs, LXC containers (via API token)
- **Portainer**: environments/endpoints and their Docker containers
- **Pi-hole (v6 API)**: devices seen on the network, local DNS records
- **Everything else** (plain Linux hosts, smart devices, anything without
  an API): add manually in Inventory, then enrich it the same way as
  discovered assets

Every asset - discovered or manual - can be enriched with notes, tags,
ports, service labels (e.g. `acme`, `nginx-proxy-manager`), and encrypted
credentials.

## Running it

```bash
docker compose up -d --build
```

Then open http://localhost:8000, go to **Connectors**, and add your
Proxmox / Portainer / Pi-hole instances. Assets appear in **Inventory**
within a few seconds of the first poll (also triggerable via "Poll now").

### Credential storage

Credentials (both connector API tokens and the ones you add for
enrichment) are encrypted at rest with Fernet (AES-128-CBC + HMAC). The
encryption key is generated on first run and stored at `/data/master.key`
inside the `netdoc-data` volume. **Back up that volume** - if the key is
lost, every stored credential is unrecoverable. Alternatively, set the
`NETDOC_MASTER_KEY` environment variable yourself (a `Fernet.generate_key()`
value) to manage the key outside the container.

### Setting up each connector

**Proxmox** - Datacenter > Permissions > API Tokens, create a token for a
user with at least the `PVEAuditor` role (read-only is enough). Enter it
as `user@realm!tokenid` + the token value.

**Portainer** - create an API key under your user's account settings, or
use a username/password.

**Pi-hole** - use your web UI password (v6 / FTL-based API only; v5's
`/admin/api.php` is not supported).

## Local development

```bash
# backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
NETDOC_DATA_DIR=./data uvicorn app.main:app --reload --port 8123

# frontend, in another shell
cd frontend
npm install
npm run dev   # http://localhost:5173, proxies /api to :8123
```

## Notes on scope

This is a deliberately small v1: three connectors, JSON blobs for
enrichment fields rather than fully normalized tables, SQLite instead of
a separate database server. It's built to extend - each connector is a
single file implementing one `poll()` method (see `backend/app/connectors/`)
that returns a flat list of discovered assets with optional
parent/child links, so adding a new source (e.g. an SSH-based Linux host
scanner, a UniFi controller) is a matter of dropping in a new connector
class rather than restructuring anything.
