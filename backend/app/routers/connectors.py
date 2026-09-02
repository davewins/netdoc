import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crypto, models, schemas
from ..database import get_db
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
