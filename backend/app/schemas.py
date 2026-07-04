import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from app.models import ResourceType, Severity


class ResourceSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resource_id: uuid.UUID
    scanned_at: datetime
    state: str
    metric_snapshot: dict[str, Any]


class FlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resource_id: uuid.UUID
    rule_type: str
    severity: Severity
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    alerted_at: Optional[datetime] = None


class FlagUpdate(BaseModel):
    resolved_at: Optional[datetime] = None


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    aws_resource_id: str
    resource_type: ResourceType
    region: str
    raw_metadata: dict[str, Any]
    first_seen_at: datetime
    last_seen_at: datetime


class ResourceDetailOut(ResourceOut):
    flags: list[FlagOut] = []
