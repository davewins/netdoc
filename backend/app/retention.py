"""Stale marking and pruning of assets a connector has stopped seeing.

Both are opt-in per connector (``stale_after_days`` / ``prune_after_days``,
null = off) and only ever look at assets that connector itself discovered and
that haven't been merged into, or out of, another source's record - so a
device Pi-hole (or any other connector) still knows about is never touched
on the strength of one source going quiet.

Run only after a poll that succeeded and returned something: a failed or
empty poll says nothing about what has gone, and an outage must never be
able to age everything out.
"""
import datetime
import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .models import Asset, AssetLink, Connector, utcnow

logger = logging.getLogger("netdoc.retention")

STALE_STATUS = "stale"
# Prune at most this share of a connector's assets in one pass (minimum
# MIN_PRUNE_CAP), as a backstop against a bug or odd poll deleting the lot.
MAX_PRUNE_SHARE = 0.25
MIN_PRUNE_CAP = 10
# Tags a connector adds on its own (e.g. RouterOS's "port:ether2"); anything
# else on an asset is treated as something a person typed in.
AUTO_TAG_PREFIXES = ("port:",)


@dataclass
class RetentionPlan:
    stale: list[Asset] = field(default_factory=list)
    prune: list[Asset] = field(default_factory=list)
    prune_blocked_by_cap: bool = False


def _is_unenriched(asset: Asset) -> bool:
    if asset.notes or asset.credentials or asset.services or asset.ports:
        return False
    return all(str(t).startswith(AUTO_TAG_PREFIXES) for t in (asset.tags or []))


def _has_relationships(asset: Asset) -> bool:
    return bool(asset.children or asset.merged_assets)


def _last_seen(asset: Asset) -> datetime.datetime | None:
    """Most recent sighting of this device by any source: its own, or that
    of a record from another source that has been merged into it."""
    seen = [a.last_seen_at for a in [asset, *asset.merged_assets] if a.last_seen_at]
    return max(seen) if seen else None


def plan_retention(db: Session, connector: Connector, now: datetime.datetime | None = None) -> RetentionPlan:
    now = now or utcnow()
    plan = RetentionPlan()
    if not connector.stale_after_days and not connector.prune_after_days:
        return plan

    own = (
        db.query(Asset)
        .filter(
            Asset.connector_id == connector.id,
            Asset.source == "discovered",
            Asset.canonical_asset_id.is_(None),
        )
        .all()
    )

    if connector.stale_after_days:
        cutoff = now - datetime.timedelta(days=connector.stale_after_days)
        plan.stale = [a for a in own if _last_seen(a) and _last_seen(a) < cutoff and a.status != STALE_STATUS]

    if connector.prune_after_days:
        cutoff = now - datetime.timedelta(days=connector.prune_after_days)
        plan.prune = [
            a
            for a in own
            if _last_seen(a)
            and _last_seen(a) < cutoff
            and not a.ip_address
            and _is_unenriched(a)
            and not _has_relationships(a)
        ]
        cap = max(MIN_PRUNE_CAP, int(len(own) * MAX_PRUNE_SHARE))
        if len(plan.prune) > cap:
            plan.prune_blocked_by_cap = True

    return plan


def apply_retention(db: Session, connector: Connector) -> None:
    plan = plan_retention(db, connector)

    for asset in plan.stale:
        asset.status = STALE_STATUS
    if plan.stale:
        logger.info("Connector %s: marked %d assets stale", connector.name, len(plan.stale))

    if plan.prune:
        names = ", ".join(sorted(a.name for a in plan.prune)[:20])
        dry_run = connector.prune_dry_run is not False
        if plan.prune_blocked_by_cap:
            logger.warning(
                "Connector %s: %d assets are prune candidates, over the safety cap - not pruning (%s)",
                connector.name, len(plan.prune), names,
            )
        elif dry_run:
            logger.info("Connector %s: dry run - would prune %d assets: %s", connector.name, len(plan.prune), names)
        else:
            for asset in plan.prune:
                db.query(AssetLink).filter(
                    (AssetLink.primary_asset_id == asset.id) | (AssetLink.secondary_asset_id == asset.id)
                ).delete(synchronize_session=False)
                db.delete(asset)
            logger.info("Connector %s: pruned %d assets: %s", connector.name, len(plan.prune), names)

    db.commit()
