from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..models import utcnow

router = APIRouter(prefix="/api/links", tags=["links"])


@router.get("", response_model=list[schemas.LinkOut])
def list_links(status: str = "pending", db: Session = Depends(get_db)):
    query = db.query(models.AssetLink)
    if status != "all":
        query = query.filter(models.AssetLink.status == status)
    return query.order_by(models.AssetLink.created_at.desc()).all()


@router.post("/{link_id}/confirm", response_model=schemas.LinkOut)
def confirm_link(link_id: int, db: Session = Depends(get_db)):
    link = db.get(models.AssetLink, link_id)
    if not link:
        raise HTTPException(404, "Link not found")

    link.status = "confirmed"
    link.updated_at = utcnow()
    primary = db.get(models.Asset, link.primary_asset_id)
    secondary = db.get(models.Asset, link.secondary_asset_id)
    secondary.canonical_asset_id = link.primary_asset_id
    primary.ip_address = primary.ip_address or secondary.ip_address
    primary.hostname = primary.hostname or secondary.hostname
    primary.status = primary.status or secondary.status
    db.commit()
    db.refresh(link)
    return link


@router.post("/{link_id}/reject", response_model=schemas.LinkOut)
def reject_link(link_id: int, db: Session = Depends(get_db)):
    link = db.get(models.AssetLink, link_id)
    if not link:
        raise HTTPException(404, "Link not found")

    link.status = "rejected"
    link.updated_at = utcnow()
    db.commit()
    db.refresh(link)
    return link
