import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Flag, Resource, ResourceSnapshot, ResourceType
from app.schemas import ResourceDetailOut, ResourceOut, ResourceSnapshotOut

router = APIRouter(prefix="/resources", tags=["resources"])


@router.get("", response_model=list[ResourceOut])
def list_resources(
    type: Optional[ResourceType] = None,
    has_flags: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Resource)
    if type is not None:
        query = query.filter(Resource.resource_type == type)
    if has_flags is not None:
        flagged_ids = db.query(Flag.resource_id).filter(Flag.resolved_at.is_(None)).distinct()
        if has_flags:
            query = query.filter(Resource.id.in_(flagged_ids))
        else:
            query = query.filter(Resource.id.notin_(flagged_ids))
    return query.all()


@router.get("/{resource_id}", response_model=ResourceDetailOut)
def get_resource(resource_id: uuid.UUID, db: Session = Depends(get_db)):
    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resource


@router.get("/{resource_id}/snapshots", response_model=list[ResourceSnapshotOut])
def get_resource_snapshots(resource_id: uuid.UUID, db: Session = Depends(get_db)):
    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    return (
        db.query(ResourceSnapshot)
        .filter(ResourceSnapshot.resource_id == resource_id)
        .order_by(ResourceSnapshot.scanned_at.desc())
        .all()
    )
