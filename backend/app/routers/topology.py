from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/topology", tags=["topology"])


@router.get("", response_model=schemas.TopologyOut)
def get_topology(db: Session = Depends(get_db)):
    assets = db.query(models.Asset).filter(models.Asset.canonical_asset_id.is_(None)).all()
    root_ids = {a.id for a in assets}

    nodes = [
        schemas.TopologyNode(
            id=a.id,
            name=a.name,
            asset_type=a.asset_type,
            status=a.status,
            ip_address=a.ip_address,
            parent_id=a.parent_id if a.parent_id in root_ids else None,
        )
        for a in assets
    ]
    edges = [
        schemas.TopologyEdge(source=a.parent_id, target=a.id, kind="parent")
        for a in assets
        if a.parent_id in root_ids
    ]

    return schemas.TopologyOut(nodes=nodes, edges=edges)
