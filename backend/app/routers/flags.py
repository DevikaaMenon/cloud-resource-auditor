import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Flag, Severity
from app.schemas import FlagOut, FlagUpdate

router = APIRouter(prefix="/flags", tags=["flags"])


@router.get("", response_model=list[FlagOut])
def list_flags(
    severity: Optional[Severity] = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
):
    query = db.query(Flag)
    if severity is not None:
        query = query.filter(Flag.severity == severity)
    if active_only:
        query = query.filter(Flag.resolved_at.is_(None))
    return query.all()


@router.patch("/{flag_id}", response_model=FlagOut)
def update_flag(flag_id: uuid.UUID, update: FlagUpdate, db: Session = Depends(get_db)):
    flag = db.query(Flag).filter(Flag.id == flag_id).first()
    if flag is None:
        raise HTTPException(status_code=404, detail="Flag not found")

    flag.resolved_at = update.resolved_at or datetime.now(timezone.utc)
    db.commit()
    db.refresh(flag)
    return flag
