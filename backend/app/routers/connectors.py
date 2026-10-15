import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crypto, models, schemas
from ..database import get_db
from ..retention import plan_retention
from ..scheduler import poll_connector

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


@router.get("", response_model=list[schemas.ConnectorOut])
def list_connectors(db: Session = Depends(get_db)):
    return db.query(models.Connector).order_by(models.Connector.name).all()


@router.post("", response_model=schemas.ConnectorOut)
def create_connector(payload: schemas.ConnectorIn, db: Session = Depends(get_db)):
    connector = models.Connector(
        type=payload.type,
        name=payload.name,
        base_url=payload.base_url,
        verify_ssl=payload.verify_ssl,
        enabled=payload.enabled,
        poll_interval_seconds=payload.poll_interval_seconds,
        site=payload.site,
        stale_after_days=payload.stale_after_days,
        prune_after_days=payload.prune_after_days,
        prune_dry_run=payload.prune_dry_run,
        encrypted_credentials=crypto.encrypt(json.dumps(payload.credentials)),
    )
    db.add(connector)
    db.commit()
    db.refresh(connector)
    return connector


@router.patch("/{connector_id}", response_model=schemas.ConnectorOut)
def update_connector(connector_id: int, payload: schemas.ConnectorIn, db: Session = Depends(get_db)):
    connector = db.get(models.Connector, connector_id)
    if not connector:
        raise HTTPException(404, "Connector not found")

    connector.type = payload.type
    connector.name = payload.name
    connector.base_url = payload.base_url
    connector.verify_ssl = payload.verify_ssl
    connector.enabled = payload.enabled
    connector.poll_interval_seconds = payload.poll_interval_seconds
    connector.site = payload.site
    # Only touch retention settings the caller actually sent, so a client
    # that predates them can't silently reset a connector's retention.
    for name in ("stale_after_days", "prune_after_days", "prune_dry_run"):
        if name in payload.model_fields_set:
            setattr(connector, name, getattr(payload, name))
    if payload.credentials:
        # Merge rather than replace: the edit UI only sends fields the user
        # actually typed into, so e.g. changing just a password shouldn't
        # blank out a username stored alongside it.
        existing = json.loads(crypto.decrypt(connector.encrypted_credentials) or "{}")
        existing.update(payload.credentials)
        connector.encrypted_credentials = crypto.encrypt(json.dumps(existing))

    db.commit()
    db.refresh(connector)
    return connector


@router.delete("/{connector_id}")
def delete_connector(connector_id: int, db: Session = Depends(get_db)):
    connector = db.get(models.Connector, connector_id)
    if not connector:
        raise HTTPException(404, "Connector not found")
    db.delete(connector)
    db.commit()
    return {"ok": True}


@router.post("/{connector_id}/poll-now", response_model=schemas.ConnectorOut)
def poll_now(connector_id: int, db: Session = Depends(get_db)):
    connector = db.get(models.Connector, connector_id)
    if not connector:
        raise HTTPException(404, "Connector not found")
    poll_connector(db, connector)
    db.refresh(connector)
    return connector


@router.get("/{connector_id}/retention-preview")
def retention_preview(connector_id: int, db: Session = Depends(get_db)):
    """What the next poll would mark stale / prune, without changing anything."""
    connector = db.get(models.Connector, connector_id)
    if not connector:
        raise HTTPException(404, "Connector not found")
    plan = plan_retention(db, connector)

    def brief(a: models.Asset):
        return {"id": a.id, "name": a.name, "mac_address": a.mac_address, "last_seen_at": a.last_seen_at}

    return {
        "stale_after_days": connector.stale_after_days,
        "prune_after_days": connector.prune_after_days,
        "prune_dry_run": connector.prune_dry_run is not False,
        "prune_blocked_by_cap": plan.prune_blocked_by_cap,
        "would_mark_stale": [brief(a) for a in plan.stale],
        "would_prune": [brief(a) for a in plan.prune],
    }
