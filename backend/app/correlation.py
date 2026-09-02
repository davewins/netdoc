import ipaddress
import logging
from collections import defaultdict

from sqlalchemy.orm import Session

from .models import Asset, AssetLink, utcnow

logger = logging.getLogger("netdoc.correlation")

# Docker's default bridge network pool. Every docker-compose stack gets its
# own isolated network carved out of this range, so e.g. "172.19.0.2" is
# extremely likely to be reused as the first container in many unrelated
# stacks - it identifies "some container's position in its own private
# network", not a real host. Matching on it produces constant false
# "same host" suggestions between totally unrelated containers, so it's
# excluded from IP-based correlation (still stored and shown on the asset
# itself, just not used as a correlation key).
_NON_CORRELATABLE_RANGES = [
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
]


def _is_correlatable_ip(ip: str | None) -> bool:
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not any(addr in net for net in _NON_CORRELATABLE_RANGES)

# Higher wins when choosing which asset becomes the canonical ("real") record
# for a group of matches. Orchestrator-defined compute (VMs/containers) beats
# passively-observed network sightings (DHCP/DNS/device/scan).
TYPE_PRIORITY = {
    "vm": 100,
    "lxc": 100,
    "docker_container": 90,
    "k8s_pod": 90,
    "docker_stack": 85,
    "docker_host": 80,
    "proxmox_node": 80,
    "k8s_node": 80,
    "dhcp_reservation": 60,
    "dns_record": 50,
    "device": 40,
    "wireguard_peer": 40,
    "ha_device": 40,
    "ha_entity": 35,
    "host": 30,
    # Purely an external observer of another asset's status, never a thing
    # in its own right - should never win canonical selection.
    "uptime_monitor": 10,
}


def _priority_key(asset: Asset):
    return (TYPE_PRIORITY.get(asset.asset_type, 0), -asset.first_seen_at.timestamp())


def _normalize_mac(mac: str | None) -> str | None:
    if not mac:
        return None
    cleaned = mac.strip().upper().replace("-", ":")
    return cleaned or None


def _resolve_root(asset: Asset, by_id: dict[int, Asset], max_depth: int = 10) -> Asset:
    current = asset
    for _ in range(max_depth):
        if current.canonical_asset_id is None:
            return current
        nxt = by_id.get(current.canonical_asset_id)
        if nxt is None or nxt.id == current.id:
            return current
        current = nxt
    return current


def _find_link(db: Session, a_id: int, b_id: int) -> AssetLink | None:
    return (
        db.query(AssetLink)
        .filter(
            ((AssetLink.primary_asset_id == a_id) & (AssetLink.secondary_asset_id == b_id))
            | ((AssetLink.primary_asset_id == b_id) & (AssetLink.secondary_asset_id == a_id))
        )
        .first()
    )


def run_correlation(db: Session) -> None:
    assets = db.query(Asset).all()
    by_id = {a.id: a for a in assets}

    # --- MAC matches: auto-merge ---
    mac_groups: dict[str, list[Asset]] = defaultdict(list)
    for a in assets:
        mac = _normalize_mac(a.mac_address)
        if mac:
            mac_groups[mac].append(a)

    for mac, group in mac_groups.items():
        if len(group) < 2:
            continue

        roots = {_resolve_root(a, by_id) for a in group}
        if len(roots) < 2:
            continue  # already all merged into the same canonical asset

        canonical = max(roots, key=_priority_key)
        for root in roots:
            if root.id == canonical.id:
                continue
            root.canonical_asset_id = canonical.id
            # Backfill anything the canonical record doesn't know itself -
            # e.g. a Proxmox VM (authoritative for specs) usually has no IP
            # until a DHCP reservation or scan tells us one.
            canonical.ip_address = canonical.ip_address or root.ip_address
            canonical.hostname = canonical.hostname or root.hostname
            canonical.status = canonical.status or root.status
            existing = _find_link(db, canonical.id, root.id)
            if existing:
                existing.status = "confirmed"
                existing.reason = "mac"
                existing.updated_at = utcnow()
            else:
                db.add(
                    AssetLink(
                        primary_asset_id=canonical.id,
                        secondary_asset_id=root.id,
                        reason="mac",
                        status="confirmed",
                    )
                )
            logger.info("Auto-merged asset %s into %s via MAC %s", root.id, canonical.id, mac)

    db.flush()

    # --- IP-only matches: suggest, don't merge ---
    # Clean up stale pending IP suggestions that no longer qualify (e.g. ones
    # created before non-correlatable ranges were excluded, or where an IP
    # has since changed).
    for link in db.query(AssetLink).filter(AssetLink.reason == "ip", AssetLink.status == "pending").all():
        primary = by_id.get(link.primary_asset_id)
        secondary = by_id.get(link.secondary_asset_id)
        still_valid = (
            primary
            and secondary
            and primary.ip_address
            and primary.ip_address == secondary.ip_address
            and _is_correlatable_ip(primary.ip_address)
        )
        if not still_valid:
            db.delete(link)
    db.flush()

    ip_groups: dict[str, list[Asset]] = defaultdict(list)
    for a in assets:
        if _is_correlatable_ip(a.ip_address):
            ip_groups[a.ip_address].append(a)

    for ip, group in ip_groups.items():
        if len(group) < 2:
            continue

        roots = {_resolve_root(a, by_id) for a in group}
        if len(roots) < 2:
            continue  # already the same canonical identity (probably via MAC)

        root_list = sorted(roots, key=_priority_key, reverse=True)

        # Reuse whichever asset was already established as this group's hub
        # in an earlier run, rather than recomputing "highest priority"
        # fresh every time. Otherwise, discovering a higher-priority asset
        # later (e.g. Portainer finding a container after Pi-hole already
        # linked its DNS records together) picks a new hub and fans out a
        # whole second set of suggestions instead of extending the first.
        group_ids = {a.id for a in root_list}
        existing_link = (
            db.query(AssetLink)
            .filter(AssetLink.reason == "ip")
            .filter(AssetLink.primary_asset_id.in_(group_ids))
            .filter(AssetLink.secondary_asset_id.in_(group_ids))
            .first()
        )
        canonical = by_id.get(existing_link.primary_asset_id) if existing_link else root_list[0]
        if canonical not in root_list:
            canonical = root_list[0]

        for other in root_list:
            if other.id == canonical.id:
                continue
            if _find_link(db, canonical.id, other.id):
                continue
            db.add(
                AssetLink(
                    primary_asset_id=canonical.id,
                    secondary_asset_id=other.id,
                    reason="ip",
                    status="pending",
                )
            )
            logger.info("Suggested link between asset %s and %s via shared IP %s", canonical.id, other.id, ip)

    db.commit()
