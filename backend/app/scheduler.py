import json
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from . import config, crypto
from .connectors import ConnectorError, build_connector
from .database import SessionLocal
from .models import Asset, Connector, utcnow

logger = logging.getLogger("netdoc.scheduler")


def poll_connector(db: Session, connector: Connector) -> None:
    try:
        creds = json.loads(crypto.decrypt(connector.encrypted_credentials) or "{}")
        client = build_connector(connector.type, connector.base_url, connector.verify_ssl, creds)
        discovered = client.poll()
    except ConnectorError as exc:
        connector.last_error = str(exc)
        connector.last_polled_at = utcnow()
        db.commit()
        logger.warning("Connector %s (%s) failed: %s", connector.name, connector.type, exc)
        return
    except Exception as exc:  # noqa: BLE001 - surface any connector bug as a poll error
        connector.last_error = f"Unexpected error: {exc}"
        connector.last_polled_at = utcnow()
        db.commit()
        logger.exception("Connector %s (%s) raised an unexpected error", connector.name, connector.type)
        return

    external_id_to_asset_id: dict[str, int] = {}

    for item in discovered:
        existing = (
            db.query(Asset)
            .filter_by(connector_id=connector.id, asset_type=item.asset_type, external_id=item.external_id)
            .one_or_none()
        )
        if existing:
            existing.name = item.name
            existing.hostname = item.hostname or existing.hostname
            existing.ip_address = item.ip_address or existing.ip_address
            existing.mac_address = item.mac_address or existing.mac_address
            existing.status = item.status
            existing.raw_data = item.raw_data
            existing.last_seen_at = utcnow()
            asset = existing
        else:
            asset = Asset(
                connector_id=connector.id,
                asset_type=item.asset_type,
                external_id=item.external_id,
                source="discovered",
                name=item.name,
                hostname=item.hostname,
                ip_address=item.ip_address,
                mac_address=item.mac_address,
                status=item.status,
                raw_data=item.raw_data,
                tags=[],
                ports=[],
                services=[],
            )
            db.add(asset)

        db.flush()
        external_id_to_asset_id[item.external_id] = asset.id

    db.flush()

    for item in discovered:
        if not item.parent_external_id:
            continue
        parent_id = external_id_to_asset_id.get(item.parent_external_id)
        if not parent_id:
            continue
        asset_id = external_id_to_asset_id[item.external_id]
        db.query(Asset).filter_by(id=asset_id).update({"parent_id": parent_id})

    connector.last_error = None
    connector.last_polled_at = utcnow()
    db.commit()
    logger.info("Connector %s (%s) discovered %d assets", connector.name, connector.type, len(discovered))


def poll_all():
    db = SessionLocal()
    try:
        for connector in db.query(Connector).filter_by(enabled=True).all():
            poll_connector(db, connector)
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(poll_all, "interval", seconds=config.POLL_INTERVAL_SECONDS, id="poll_all")
    scheduler.add_job(poll_all, "date", id="poll_all_initial")
    scheduler.start()
    return scheduler
