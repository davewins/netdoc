# netdoc

A self-hosted network inventory tool: it polls Proxmox, Portainer and
Pi-hole to automatically discover what's running on your network, actively
scans the LAN for anything those don't know about, cross-references all
of it into one picture per physical/virtual host, and gives you a web UI
to enrich each one with the details no API exposes - ports, credentials,
notes, "what service is this actually running" tags.

v1 is read-only against your infrastructure: it only ever calls list/read
API endpoints, never changes anything on Proxmox/Portainer/Pi-hole.

## What it discovers

- **Proxmox VE**: nodes, VMs, LXC containers - status, vCPU/RAM/disk,
  tags, and MAC address (from config, so it's known even when stopped)
  plus IP address where the guest agent (VMs) or `pct` interfaces (LXC)
  can report one
- **Portainer**: environments/endpoints, stacks, and their Docker
  containers - status, resource limits, IP/MAC, published ports, and a
  best-effort service guess from the image name (e.g. `traefik`,
  `acme`, `home-assistant`)
- **Pi-hole (v6 API)**: devices seen on the network, local DNS records,
  and DHCP reservations/leases (MAC+IP+hostname - the strongest link back
  to a Proxmox VM's NIC)
- **Network scan (nmap)**: ARP/ping sweep of a CIDR range plus a light
  port scan, for anything the above don't know about
- **Everything else** (plain Linux hosts, smart devices, anything without
  an API): add manually in Inventory, then enrich it the same way as
  discovered assets

Every asset - discovered or manual - can be enriched with notes, tags,
ports, service labels, and encrypted credentials.

## Cross-referencing

The same physical/virtual host is usually discovered more than once - a
Proxmox VM, its Pi-hole DHCP reservation, and a network-scan hit are all
"the same box" as far as you're concerned. netdoc correlates these
automatically:

- **Same MAC address → merged automatically.** MACs don't get reassigned,
  so these are treated as certain. The record from the more authoritative
  source (a VM/container beats a passively-observed DNS/DHCP/scan entry)
  becomes the one shown in Inventory, and inherits any IP/hostname the
  merged-in records knew that it didn't.
- **Same IP address only → suggested, not merged.** DHCP can reassign an
  IP, and several hostnames legitimately sharing one reverse-proxy IP
  isn't the same as being one host - so these show up in **Link
  suggestions** for you to confirm or reject (bulk actions available when
  one record shares an IP with many others, e.g. every subdomain behind
  one reverse proxy).

Merged/confirmed records show up as one entry in Inventory with an "Also
known as" section on its detail page; Inventory's own counts and the
**Network map** only count each host once.

## Network map

A live, auto-refreshing diagram of everything in Inventory (grouped
Proxmox node → VM/LXC and Docker host/stack → container), styled by type.
Double-click a node to open its detail page.

## Running it

```bash
docker compose up -d --build
```

Then open the app on port 8000 and go to **Connectors** to add your
Proxmox / Portainer / Pi-hole instances, and optionally a network-scan
connector (CIDR range, e.g. `192.168.1.0/24`). Assets appear in
**Inventory** within a few seconds of the first poll (also triggerable
via "Poll now").

### Host networking (for the network-scan connector)

`docker-compose.yml` runs the container with `network_mode: host` and
`NET_ADMIN`/`NET_RAW` capabilities so nmap's ARP scan can see real
devices on your LAN rather than just Docker's own bridge network. This
**only works on a Linux Docker host** - Docker Desktop (Mac/Windows)
doesn't give containers real host network access, so on those platforms
the app itself still works fine, but the network-scan connector won't
find anything and the container won't be reachable via `localhost` (it
binds to the host-networking namespace, which Docker Desktop's VM
doesn't expose to your Mac/Windows host that way). If you don't need
active scanning, remove `network_mode: host` / `cap_add` and add a
normal `ports: ["8000:8000"]` mapping instead.

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

**Network scan** - just a CIDR range (entered as the connector's "base
URL" field), no credentials. Requires host networking (see above).

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

JSON blobs for enrichment fields rather than fully normalized tables,
SQLite instead of a separate database server, additive-only ALTER TABLE
migrations (fine for a single-user homelab app, not a general migration
framework). It's built to extend - each connector is a single file
implementing one `poll()` method (see `backend/app/connectors/`) that
returns a flat list of discovered assets with optional parent/child
links and spec fields, so adding a new source (e.g. a UniFi controller)
is a matter of dropping in a new connector class rather than
restructuring anything.
