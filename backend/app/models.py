import uuid
import enum

from sqlalchemy import Column, String, DateTime, ForeignKey, Enum, func
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship

from app.database import Base


class ResourceType(str, enum.Enum):
    ec2 = "ec2"
    ebs_volume = "ebs_volume"


class Severity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Resource(Base):
    __tablename__ = "resources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aws_resource_id = Column(String, index=True, nullable=False)
    resource_type = Column(Enum(ResourceType, name="resource_type"), nullable=False)
    region = Column(String, nullable=False)
    raw_metadata = Column(JSON, nullable=False)
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    snapshots = relationship(
        "ResourceSnapshot", back_populates="resource", cascade="all, delete-orphan"
    )
    flags = relationship(
        "Flag", back_populates="resource", cascade="all, delete-orphan"
    )


class ResourceSnapshot(Base):
    __tablename__ = "resource_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_id = Column(UUID(as_uuid=True), ForeignKey("resources.id", ondelete="CASCADE"), nullable=False)
    scanned_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    state = Column(String, nullable=False)
    metric_snapshot = Column(JSON, nullable=False)

    resource = relationship("Resource", back_populates="snapshots")


class Flag(Base):
    __tablename__ = "flags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_id = Column(UUID(as_uuid=True), ForeignKey("resources.id", ondelete="CASCADE"), nullable=False)
    rule_type = Column(String, nullable=False)
    severity = Column(Enum(Severity, name="severity"), nullable=False)
    detected_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    alerted_at = Column(DateTime(timezone=True), nullable=True)

    resource = relationship("Resource", back_populates="flags")
