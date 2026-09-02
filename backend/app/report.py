"""Builds the "commentary" writeup shown on the Report page (and exposed to
MCP clients via the get_network_report tool) from the current database
state. Deliberately template-based rather than backed by any LLM call - this
is a self-hosted, dependency-light app and the source data (counts, a
handful of status strings) doesn't need one to read as a short, useful
summary.
"""

from collections import Counter

from sqlalchemy.orm import Session

from . import models

SITE_LABEL_LOCAL = "Local network"

# Connectors report status in whatever vocabulary their upstream API uses
# (proxmox: "stopped", portainer: "exited"/"down", uptime_kuma: "down", k8s
# pod phases, HA entity states, ...) - there's no single enum across them
# (see connectors/*.py). Rather than special-case every source, this is a
# best-effort scan for common "not up" keywords, so the report's "needs
# attention" section is approximate by design, not a precise health check.
NEGATIVE_STATUS_KEYWORDS = {"down", "stopped", "exited", "off", "inactive", "dead", "failed", "error"}


def _visible_assets(db: Session) -> list[models.Asset]:
    # Same visibility rules as the default inventory list and the topology
    # graph: skip assets merged into another record, and skip Home
    # Assistant entities that belong to a device (sub-components, not
    # independently significant - see routers/inventory.py).
    return (
        db.query(models.Asset)
        .filter(models.Asset.canonical_asset_id.is_(None))
        .filter(~((models.Asset.asset_type == "ha_entity") & (models.Asset.parent_id.isnot(None))))
        .all()
    )


def _is_down(asset: models.Asset) -> bool:
    return bool(asset.status) and asset.status.strip().lower() in NEGATIVE_STATUS_KEYWORDS


def _format_type(asset_type: str) -> str:
    return asset_type.replace("_", " ")


def _top_types(counts: Counter, n: int = 3) -> str:
    parts = [f"{count} {_format_type(t)}{'s' if count != 1 else ''}" for t, count in counts.most_common(n)]
    return ", ".join(parts)


def _pluralize(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def _compose_narrative(
    *,
    total: int,
    by_type: Counter,
    by_site: Counter,
    connectors: list[models.Connector],
    down_assets: list[models.Asset],
    failing_connectors: list[models.Connector],
    pending_link_count: int,
) -> list[str]:
    if total == 0:
        return ["No assets have been discovered yet. Add a connector or run a network scan to get started."]

    paragraphs: list[str] = []
    site_names = sorted(s for s in by_site if s != SITE_LABEL_LOCAL)
    local_count = by_site.get(SITE_LABEL_LOCAL, 0)

    if site_names:
        # Every connector can end up tagged with some site, leaving nothing
        # untagged at all - phrase this without an awkward "and the
        # remaining 0 are on the main network" when that's the case, rather
        # than assuming there's always an implicit main-network group.
        network_bit = "the main network and " if local_count else ""
        paragraphs.append(
            f"netdoc is currently tracking {total} assets across {network_bit}"
            f"{_pluralize(len(site_names), 'tagged site')} ({', '.join(site_names)}), discovered via "
            f"{_pluralize(len(connectors), 'connector')}. The most common kinds of asset are {_top_types(by_type)}."
        )
        site_bits = [f"{s} has {_pluralize(by_site[s], 'asset')}" for s in site_names]
        by_site_sentence = "By site: " + "; ".join(site_bits)
        if local_count:
            by_site_sentence += f", and the remaining {_pluralize(local_count, 'asset')} are on the main network."
        else:
            by_site_sentence += ". Every asset is on a tagged site - there's no untagged main network left."
        paragraphs.append(by_site_sentence)
    else:
        paragraphs.append(
            f"netdoc is currently tracking {total} assets on the main network, discovered via "
            f"{_pluralize(len(connectors), 'connector')}. The most common kinds of asset are {_top_types(by_type)}."
        )

    health_bits = []
    if failing_connectors:
        names = ", ".join(c.name for c in failing_connectors[:5])
        more = f" and {len(failing_connectors) - 5} more" if len(failing_connectors) > 5 else ""
        health_bits.append(f"{_pluralize(len(failing_connectors), 'connector')} currently failing to poll ({names}{more})")
    if down_assets:
        names = ", ".join(a.name for a in down_assets[:5])
        more = f" and {len(down_assets) - 5} more" if len(down_assets) > 5 else ""
        health_bits.append(f"{_pluralize(len(down_assets), 'asset')} reporting a down/stopped/offline-ish status ({names}{more})")
    if pending_link_count:
        health_bits.append(f"{_pluralize(pending_link_count, 'pending link suggestion')} awaiting review")

    if health_bits:
        paragraphs.append("Needs attention: " + "; ".join(health_bits) + ".")
    else:
        paragraphs.append(
            "Nothing currently needs attention: no connectors are failing, no tracked asset is reporting "
            "a down status, and there are no pending link suggestions."
        )

    return paragraphs


def build_report(db: Session) -> dict:
    assets = _visible_assets(db)
    connectors = db.query(models.Connector).order_by(models.Connector.name).all()
    pending_link_count = db.query(models.AssetLink).filter(models.AssetLink.status == "pending").count()

    by_type = Counter(a.asset_type for a in assets)
    by_site = Counter((a.site or SITE_LABEL_LOCAL) for a in assets)
    down_assets = [a for a in assets if _is_down(a)]
    failing_connectors = [c for c in connectors if c.last_error]

    narrative = _compose_narrative(
        total=len(assets),
        by_type=by_type,
        by_site=by_site,
        connectors=connectors,
        down_assets=down_assets,
        failing_connectors=failing_connectors,
        pending_link_count=pending_link_count,
    )

    return {
        "generated_at": models.utcnow().isoformat(),
        "total_assets": len(assets),
        "by_type": dict(by_type),
        "by_site": dict(by_site),
        "connectors": [
            {
                "id": c.id,
                "name": c.name,
                "type": c.type,
                "site": c.site,
                "enabled": c.enabled,
                "last_polled_at": c.last_polled_at.isoformat() if c.last_polled_at else None,
                "last_error": c.last_error,
            }
            for c in connectors
        ],
        "down_assets": [
            {"id": a.id, "name": a.name, "asset_type": a.asset_type, "status": a.status, "site": a.site}
            for a in down_assets
        ],
        "pending_link_count": pending_link_count,
        "narrative": narrative,
    }
