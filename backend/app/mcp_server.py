"""Exposes netdoc's inventory to MCP clients (e.g. Claude Desktop/Code) over
Streamable HTTP, mounted at /mcp by main.py.

Scope is deliberately "read + light actions": querying assets/topology/
connectors/links and the narrative report, plus triggering a connector poll
or confirming/rejecting a pending link suggestion. No credential reveal, and
no asset/connector create/update/delete - see CLAUDE.md for the reasoning.

Tool bodies open their own DB session and call straight into the existing
router functions (passing `db=` explicitly, since FastAPI's `Depends(get_db)`
default only resolves when a function is invoked through the ASGI request
path - calling it directly as plain Python just uses whatever you pass) so
there's one source of truth for each query/mutation instead of a second copy
of the logic living here.
"""

import secrets

from mcp.server.fastmcp import FastMCP

from . import config, schemas
from .database import SessionLocal
from .report import build_report
from .routers import connectors as connectors_router
from .routers import inventory as inventory_router
from .routers import links as links_router
from .routers import topology as topology_router


def _load_or_create_mcp_token() -> str:
    if config.MCP_TOKEN_ENV:
        return config.MCP_TOKEN_ENV
    if config.MCP_TOKEN_PATH.exists():
        return config.MCP_TOKEN_PATH.read_text().strip()
    token = secrets.token_urlsafe(32)
    config.MCP_TOKEN_PATH.write_text(token)
    config.MCP_TOKEN_PATH.chmod(0o600)
    return token


MCP_TOKEN = _load_or_create_mcp_token()

mcp = FastMCP(
    name="netdoc",
    instructions=(
        "Query a self-hosted homelab network inventory: assets discovered from Proxmox, Portainer, "
        "Pi-hole, Home Assistant, Kubernetes, Uptime Kuma, WireGuard and an active LAN scan, "
        "cross-referenced into one entry per real host. Mostly read-only, plus a couple of light "
        "actions: triggering an immediate connector poll, and confirming/rejecting a pending "
        "same-host link suggestion. Credentials are never exposed through this server - use the "
        "netdoc web UI directly for those."
    ),
    stateless_http=True,
    # main.py mounts streamable_http_app() at /mcp - FastMCP's own default
    # internal route path is *also* "/mcp", which would double up into
    # /mcp/mcp if left alone. Rooting it at "/" makes the outer mount
    # prefix the only "/mcp" in the final URL.
    streamable_http_path="/",
)


@mcp.tool()
def list_assets(
    asset_type: str | None = None,
    site: str | None = None,
    q: str | None = None,
    connector_id: int | None = None,
) -> list[dict]:
    """List discovered/tracked network assets. Filter by asset_type (e.g. "vm", "docker_container",
    "device"), by site (a connector's tagged remote location, e.g. "Site A"; omit for everything),
    by connector_id, or search name/hostname/IP with q."""
    db = SessionLocal()
    try:
        assets = inventory_router.list_assets(asset_type=asset_type, connector_id=connector_id, site=site, q=q, db=db)
        return [a.model_dump(mode="json") for a in assets]
    finally:
        db.close()


@mcp.tool()
def get_asset(asset_id: int) -> dict:
    """Get full detail for one asset by id: enrichment (notes/tags/ports/services), hardware/status
    fields, linked assets from other sources, and child assets (e.g. a Proxmox node's VMs)."""
    db = SessionLocal()
    try:
        return inventory_router.get_asset(asset_id, db=db).model_dump(mode="json")
    finally:
        db.close()


@mcp.tool()
def get_topology() -> dict:
    """Get the network topology graph (nodes plus parent/child edges) that backs the live network map."""
    db = SessionLocal()
    try:
        return topology_router.get_topology(db=db).model_dump(mode="json")
    finally:
        db.close()


@mcp.tool()
def list_connectors() -> list[dict]:
    """List configured data-source connectors (Proxmox, Portainer, Pi-hole, etc.), their type, tagged
    site, and poll status (last polled time or last error)."""
    db = SessionLocal()
    try:
        connectors = connectors_router.list_connectors(db=db)
        return [schemas.ConnectorOut.model_validate(c).model_dump(mode="json") for c in connectors]
    finally:
        db.close()


@mcp.tool()
def poll_connector_now(connector_id: int) -> dict:
    """Trigger an immediate poll of one connector instead of waiting for its scheduled interval."""
    db = SessionLocal()
    try:
        connector = connectors_router.poll_now(connector_id, db=db)
        return schemas.ConnectorOut.model_validate(connector).model_dump(mode="json")
    finally:
        db.close()


@mcp.tool()
def list_pending_links(status: str = "pending") -> list[dict]:
    """List same-host link suggestions: pairs of assets from different sources that share an IP and may
    be the same real device. status is "pending" (default), "confirmed", "rejected", or "all"."""
    db = SessionLocal()
    try:
        links = links_router.list_links(status=status, db=db)
        return [schemas.LinkOut.model_validate(link).model_dump(mode="json") for link in links]
    finally:
        db.close()


@mcp.tool()
def confirm_link(link_id: int) -> dict:
    """Confirm a pending link suggestion - the two records are the same real host, so the secondary is
    merged into the primary."""
    db = SessionLocal()
    try:
        link = links_router.confirm_link(link_id, db=db)
        return schemas.LinkOut.model_validate(link).model_dump(mode="json")
    finally:
        db.close()


@mcp.tool()
def reject_link(link_id: int) -> dict:
    """Reject a pending link suggestion - the two records are not the same host and should stay separate."""
    db = SessionLocal()
    try:
        link = links_router.reject_link(link_id, db=db)
        return schemas.LinkOut.model_validate(link).model_dump(mode="json")
    finally:
        db.close()


@mcp.tool()
def get_network_report() -> dict:
    """Get a narrative commentary/summary of the current network state: inventory totals broken down by
    asset type and site, connectors currently failing to poll, assets reporting a down/stopped/offline-ish
    status, and the count of pending link suggestions - the same content shown on the Report page."""
    db = SessionLocal()
    try:
        return build_report(db)
    finally:
        db.close()
