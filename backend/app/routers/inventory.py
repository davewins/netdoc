from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..correlation import run_correlation
from ..database import get_db

router = APIRouter(prefix="/api/assets", tags=["assets"])


def _serialize(db: Session, asset: models.Asset) -> schemas.AssetOut:
    out = schemas.AssetOut.model_validate(asset)

    links = (
        db.query(models.AssetLink)
        .filter(models.AssetLink.primary_asset_id == asset.id, models.AssetLink.status == "confirmed")
        .all()
    )
    linked = []
    for link in links:
        other = link.secondary_asset
        linked.append(
            schemas.LinkedAssetOut(
                id=other.id,
                asset_type=other.asset_type,
                name=other.name,
                ip_address=other.ip_address,
                mac_address=other.mac_address,
                connector_id=other.connector_id,
                link_reason=link.reason,
                link_status=link.status,
            )
        )
    out.linked_assets = linked

    children = db.query(models.Asset).filter(models.Asset.parent_id == asset.id).all()
    out.children = [
        schemas.ChildAssetOut(id=c.id, asset_type=c.asset_type, name=c.name, status=c.status, ports=c.ports or [])
        for c in children
    ]
    return out


@router.get("", response_model=list[schemas.AssetOut])
def list_assets(
    asset_type: Optional[str] = None,
    connector_id: Optional[int] = None,
    site: Optional[str] = None,
    q: Optional[str] = None,
    include_merged: bool = False,
    include_child_entities: bool = False,
    db: Session = Depends(get_db),
):
    query = db.query(models.Asset)
    if not include_merged:
        query = query.filter(models.Asset.canonical_asset_id.is_(None))
    if not include_child_entities and not q:
        # Home Assistant entities that belong to a device (e.g. a WLED
        # strip's light + 5 helper switches, or a smart display's backlight
        # + relays) are sub-components, not independently significant
        # assets - the device itself is what belongs in the default list.
        # Unlike Proxmox/Docker/k8s parent-child pairs (a VM or container is
        # still worth its own row even though it has a parent), so this is
        # scoped to ha_entity specifically rather than "any asset with a
        # parent". Skipped when searching, so a search for e.g. "backlight"
        # still finds the entity it's actually asking about.
        query = query.filter(
            ~((models.Asset.asset_type == "ha_entity") & (models.Asset.parent_id.isnot(None)))
        )
    if asset_type:
        query = query.filter(models.Asset.asset_type == asset_type)
    if connector_id is not None:
        query = query.filter(models.Asset.connector_id == connector_id)
    if site:
        # Manual assets have no connector_id at all - an inner join is
        # exactly right here, since they can't belong to any site.
        query = query.join(models.Connector).filter(models.Connector.site == site)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (models.Asset.name.ilike(like))
            | (models.Asset.hostname.ilike(like))
            | (models.Asset.ip_address.ilike(like))
        )
    assets = query.order_by(models.Asset.asset_type, models.Asset.name).all()
    return [_serialize(db, a) for a in assets]


@router.get("/{asset_id}", response_model=schemas.AssetOut)
def get_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = db.get(models.Asset, asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")
    return _serialize(db, asset)


@router.post("", response_model=schemas.AssetOut)
def create_asset(payload: schemas.AssetCreateManual, db: Session = Depends(get_db)):
    asset = models.Asset(source="manual", **payload.model_dump())
    db.add(asset)
    db.commit()
    db.refresh(asset)
    run_correlation(db)
    db.refresh(asset)
    return _serialize(db, asset)


@router.patch("/{asset_id}", response_model=schemas.AssetOut)
def enrich_asset(asset_id: int, payload: schemas.AssetEnrichmentIn, db: Session = Depends(get_db)):
    asset = db.get(models.Asset, asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")

    data = payload.model_dump(exclude_unset=True)
    if "ports" in data and data["ports"] is not None:
        data["ports"] = [p if isinstance(p, dict) else p.model_dump() for p in payload.ports]
    for field, value in data.items():
        setattr(asset, field, value)

    db.commit()
    db.refresh(asset)
    return _serialize(db, asset)


@router.delete("/{asset_id}")
def delete_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = db.get(models.Asset, asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")

    # Un-merge anything that pointed to this asset as its canonical record,
    # and drop link rows referencing it, so deleting a merge target doesn't
    # leave dangling references behind.
    db.query(models.Asset).filter(models.Asset.canonical_asset_id == asset_id).update(
        {"canonical_asset_id": None}
    )
    db.query(models.AssetLink).filter(
        (models.AssetLink.primary_asset_id == asset_id) | (models.AssetLink.secondary_asset_id == asset_id)
    ).delete()

    db.delete(asset)
    db.commit()
    return {"ok": True}
