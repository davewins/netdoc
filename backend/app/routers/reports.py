from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..report import build_report

router = APIRouter(prefix="/api/report", tags=["report"])


@router.get("", response_model=schemas.ReportOut)
def get_report(db: Session = Depends(get_db)):
    return build_report(db)
