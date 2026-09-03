# netdoc

A self-hosted network inventory tool: it polls Proxmox, Portainer and
Pi-hole to automatically discover what's running on your network, actively
scans the LAN for anything those don't know about, cross-references all
of it into one picture per physical/virtual host, and gives you a web UI
to enrich each one with the details no API exposes - ports, credentials,
notes, "what service is this actually running" tags.

I built this to document my own homelab. I'd accumulated VMs, LXC
containers, Docker stacks, and a pile of other self-hosted services across
a couple of sites and had no single up-to-date picture of what was running
where or on what port - and every "network documentation" tool I found was
either a manual CMDB (you type everything in yourself and it rots the
moment you forget to update it) or pure discovery with nowhere to hang
notes/credentials/ports on what it found. I wanted both halves in one
thing I could just run against my own infrastructure, so this is that.

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
- **Home Assistant**: entities from device-ish domains (lights, switches,
  climate, cameras, locks, covers, fans, media players, vacuums, device
  trackers), plus anything else that happens to expose an IP/MAC. Grouped
  under one `ha_device` asset per physical device (a WLED strip's light +
  5 helper switches, a smart display's backlight + relays, ...) - fetched
  via a `/api/template` call, since the REST API's `/api/states` alone has
  no notion of "device". An entity that belongs to a device is hidden from
  Inventory/the network map by default (it's a sub-component, not its own
  thing) but still reachable from its device's page, or via search
- **Kubernetes**: nodes (with real IP, so a node usually auto-merges with
  its already-discovered Proxmox VM) and pods, grouped under their node
- **Uptime Kuma**: doesn't discover new hosts - backfills the `status`
  field on assets discovered elsewhere, via its Prometheus metrics
  endpoint. Each monitor becomes its own low-priority asset that links up
  with an existing one by IP (resolved from the monitor's hostname where
  needed); confirming that link in **Link suggestions** is what applies
  the backfill
- **WireGuard (wg-easy or WGDashboard)**: VPN peers - name, tunnel IP, and
  a connected/disconnected/disabled status derived from the last
  handshake time. Two separate connector types, since these are two
  unrelated self-hosted WireGuard UIs with their own APIs (WireGuard
  itself has no API of its own) - pick whichever one a given instance
  actually runs. wg-easy targets the v14+ Nuxt-based rewrite; the older
  pre-v14 build isn't supported. WGDashboard doesn't support an account
  with TOTP enabled (no way to supply a live code from a poll loop).
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
  source (a VM/container beats a passively-observed DNS/DHCP/scan entry,
  which beats a pure external observer like an Uptime Kuma monitor)
  becomes the one shown in Inventory, and inherits any IP/hostname/status
  the merged-in records knew that it didn't.
- **Same IP address only → suggested, not merged.** DHCP can reassign an
  IP, and several hostnames legitimately sharing one reverse-proxy IP
  isn't the same as being one host - so these show up in **Link
  suggestions** for you to confirm or reject (bulk actions available when
  one record shares an IP with many others, e.g. every subdomain behind
  one reverse proxy). Confirming applies the same ip/hostname/status
  backfill as an automatic MAC merge does.

Merged/confirmed records show up as one entry in Inventory with an "Also
known as" section on its detail page; Inventory's own counts and the
**Network map** only count each host once.

## Sites

Give a connector a "Site" (in Connectors, e.g. "Site A") if it talks
to a second physical location rather than your main network - every asset
it discovers inherits that label. Inventory can filter by it, Dashboard
gets an "Other sites" breakdown, and Network map draws a colored ring
around that site's nodes (see the map's own legend for which color is
which). Leave it blank for connectors on your main network - there's no
special "home site" label, just the absence of one.

## Network map

A live, auto-refreshing diagram of everything in Inventory (grouped
Proxmox node → VM/LXC and Docker host/stack → container), styled by type,
with a legend below the graph for the shape/color per type and (if any
connector has a site set) the ring color per site. Double-click a node to
open its detail page.

## Report

A generated-on-demand narrative summary of the current network state -
inventory totals by type and site, connectors currently failing to poll,
assets reporting a down/stopped/offline-ish status, and any pending link
suggestions. Nothing is stored or scheduled; it's recomputed from the
database every time you open the page or hit "Regenerate". The same
content is available to an MCP client via the `get_network_report` tool
below.

## MCP server (querying from Claude)

netdoc exposes a Model Context Protocol server at `/mcp` (Streamable HTTP)
so a Claude client can query and lightly act on your inventory directly -
list/search assets, get an asset's full detail, get the topology graph,
list connectors, get the report above, trigger an immediate connector
poll, or confirm/reject a pending link suggestion. Credential data is
never exposed through this server, and neither is creating, editing, or
deleting an asset or connector - use the web UI for those.

The rest of netdoc's API has no authentication at all, which is fine for
a UI that's only ever hit from a trusted LAN - but `/mcp` is meant to be
reachable more broadly (any MCP client, any machine on the network), so
it's gated behind a single shared bearer token. The token is generated on
first run and persisted at `/data/mcp_token` inside the data volume (or
set explicitly via the `NETDOC_MCP_TOKEN` environment variable); find it
with:

```bash
docker exec netdoc cat /data/mcp_token
```

Then point an MCP client at `http://<host>:<port>/mcp/` with that token as
a bearer `Authorization` header - for example, with Claude Code:

```bash
claude mcp add --transport http netdoc http://<host>:<port>/mcp/ \
  --header "Authorization: Bearer <token>"
```

(Keep the trailing slash - `/mcp` without one 307-redirects to `/mcp/`,
which most clients follow automatically, but not all do.)

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

**Home Assistant** - Profile (click your name, bottom left) > Security >
Long-Lived Access Tokens > Create Token.

**Kubernetes** - create a read-only service account and grab its token:
```bash
kubectl create serviceaccount netdoc -n default
kubectl create clusterrolebinding netdoc-view --clusterrole=view --serviceaccount=default:netdoc
kubectl create token netdoc -n default
```
Point the connector at the cluster's API server (`kubectl cluster-info`).
Self-signed cluster CAs are normal - leave "Verify TLS certificate" off
unless you've supplied that CA to the container.

**Uptime Kuma** - enable "Expose Prometheus Metrics" in Settings, then use
an API key (Settings > API Keys) or your login username/password.

**WireGuard (wg-easy or WGDashboard)** - use the username/password you log
into whichever web UI with. WGDashboard accounts with TOTP enabled aren't
supported.

### Reaching a second site over an existing tunnel

If the netdoc host already has a route to a remote network (e.g. a
site-to-site WireGuard tunnel to another location), connectors work
against it exactly like the local LAN - `network_mode: host` means netdoc
shares the host's full routing table, tunnel interfaces included. Point a
second Proxmox/Portainer/Pi-hole connector at that site's own instance, or
add another network-scan connector with its CIDR (e.g. `10.20.0.0/24`),
the same way you'd run two of any connector type for two separate sites.
One caveat specific to network-scan: its host-discovery pass relies on
ARP, which only works on the local broadcast segment - across a routed
tunnel there's no L2 to ARP on at all, so it falls back to ping/TCP
probes. Remote hosts are still found, just without a MAC address (and
therefore without the "same MAC → auto-merge" correlation that local scan
hits get) - and if a remote device doesn't answer ICMP or any of the
scanned ports, it won't be found at all, no matter how the connector is
tuned. If a remote scan finds far fewer devices than you expect, it's
worth checking from the remote end: is the tunnel peer actually routing/
NATing to the rest of that LAN (IP forwarding enabled, the peer's
AllowedIPs covers the whole subnet, not just its own tunnel address), or
is it only reachable itself.

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
