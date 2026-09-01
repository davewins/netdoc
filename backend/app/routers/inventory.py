from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.get("", response_model=list[schemas.AssetOut])
def list_assets(
    asset_type: Optional[str] = None,
    connector_id: Optional[int] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Asset)
    if asset_type:
        query = query.filter(models.Asset.asset_type == asset_type)
    if connector_id is not None:
        query = query.filter(models.Asset.connector_id == connector_id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (models.Asset.name.ilike(like))
            | (models.Asset.hostname.ilike(like))
            | (models.Asset.ip_address.ilike(like))
        )
    return query.order_by(models.Asset.asset_type, models.Asset.name).all()


@router.get("/{asset_id}", response_model=schemas.AssetOut)
def get_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = db.get(models.Asset, asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")
    return asset


@router.post("", response_model=schemas.AssetOut)
def create_asset(payload: schemas.AssetCreateManual, db: Session = Depends(get_db)):
    asset = models.Asset(source="manual", **payload.model_dump())
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


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
    return asset


@router.delete("/{asset_id}")
def delete_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = db.get(models.Asset, asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")
    db.delete(asset)
    db.commit()
    return {"ok": True}
