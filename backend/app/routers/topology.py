from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/topology", tags=["topology"])


@router.get("", response_model=schemas.TopologyOut)
def get_topology(db: Session = Depends(get_db)):
    # Home Assistant entities belonging to a device are sub-components, not
    # nodes worth their own place in the graph (see the same exclusion,
    # with fuller reasoning, in routers/inventory.py's list_assets) - with
    # potentially dozens of them per device this isn't just decluttering,
    # it's the difference between a readable graph and a hairball.
    assets = (
        db.query(models.Asset)
        .filter(models.Asset.canonical_asset_id.is_(None))
        .filter(~((models.Asset.asset_type == "ha_entity") & (models.Asset.parent_id.isnot(None))))
        .all()
    )
    root_ids = {a.id for a in assets}

    nodes = [
        schemas.TopologyNode(
            id=a.id,
            name=a.name,
            asset_type=a.asset_type,
            status=a.status,
            ip_address=a.ip_address,
            site=a.site,
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
