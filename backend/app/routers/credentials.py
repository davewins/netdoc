from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crypto, models, schemas
from ..database import get_db

router = APIRouter(tags=["credentials"])


@router.post("/api/assets/{asset_id}/credentials", response_model=schemas.CredentialOut)
def add_credential(asset_id: int, payload: schemas.CredentialIn, db: Session = Depends(get_db)):
    asset = db.get(models.Asset, asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")

    cred = models.Credential(
        asset_id=asset_id,
        label=payload.label,
        username=payload.username,
        encrypted_secret=crypto.encrypt(payload.secret),
        notes=payload.notes,
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return cred


@router.patch("/api/credentials/{credential_id}", response_model=schemas.CredentialOut)
def update_credential(credential_id: int, payload: schemas.CredentialIn, db: Session = Depends(get_db)):
    cred = db.get(models.Credential, credential_id)
    if not cred:
        raise HTTPException(404, "Credential not found")

    cred.label = payload.label
    cred.username = payload.username
    cred.notes = payload.notes
    if payload.secret:
        cred.encrypted_secret = crypto.encrypt(payload.secret)

    db.commit()
    db.refresh(cred)
    return cred


@router.get("/api/credentials/{credential_id}/reveal", response_model=schemas.CredentialRevealed)
def reveal_credential(credential_id: int, db: Session = Depends(get_db)):
    cred = db.get(models.Credential, credential_id)
    if not cred:
        raise HTTPException(404, "Credential not found")

    return schemas.CredentialRevealed(
        id=cred.id,
        asset_id=cred.asset_id,
        label=cred.label,
        username=cred.username,
        notes=cred.notes,
        created_at=cred.created_at,
        updated_at=cred.updated_at,
        secret=crypto.decrypt(cred.encrypted_secret),
    )


@router.delete("/api/credentials/{credential_id}")
def delete_credential(credential_id: int, db: Session = Depends(get_db)):
    cred = db.get(models.Credential, credential_id)
    if not cred:
        raise HTTPException(404, "Credential not found")
    db.delete(cred)
    db.commit()
    return {"ok": True}
