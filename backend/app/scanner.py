"""EC2 + EBS scanning and rule-based flagging.

Scanning and detection are kept as plain functions (not a generic rule
engine) per the project's "clarity over cleverness for v1" guidance.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from sqlalchemy.orm import Session

from app.models import Flag, Resource, ResourceSnapshot, ResourceType, Severity

IDLE_EC2_CPU_THRESHOLD = 5.0
IDLE_EC2_MIN_RUNNING_HOURS = 24
UNATTACHED_EBS_MIN_HOURS = 1


def get_resource_tags(resource_type: ResourceType, raw_metadata: dict[str, Any]) -> dict[str, str]:
    """EC2 and EBS represent tags differently in their raw boto3 shape."""
    tags = raw_metadata.get("Tags") or []
    return {tag["Key"]: tag["Value"] for tag in tags}


def _upsert_resource(
    db: Session,
    resource_type: ResourceType,
    aws_resource_id: str,
    region: str,
    raw_metadata: dict[str, Any],
) -> Resource:
    resource = (
        db.query(Resource)
        .filter(
            Resource.aws_resource_id == aws_resource_id,
            Resource.resource_type == resource_type,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if resource is None:
        resource = Resource(
            aws_resource_id=aws_resource_id,
            resource_type=resource_type,
            region=region,
            raw_metadata=raw_metadata,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(resource)
    else:
        resource.raw_metadata = raw_metadata
        resource.last_seen_at = now
    db.flush()
    return resource


def scan_ec2_instances(db: Session, region: str) -> list[Resource]:
    ec2 = boto3.client("ec2", region_name=region)
    cloudwatch = boto3.client("cloudwatch", region_name=region)
    resources: list[Resource] = []

    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                instance_id = instance["InstanceId"]
                state = instance["State"]["Name"]
                resource = _upsert_resource(db, ResourceType.ec2, instance_id, region, instance)

                cpu_avg = None
                if state == "running":
                    cpu_avg = _get_ec2_avg_cpu(cloudwatch, instance_id)

                db.add(
                    ResourceSnapshot(
                        resource_id=resource.id,
                        scanned_at=datetime.now(timezone.utc),
                        state=state,
                        metric_snapshot={"cpu_avg": cpu_avg} if cpu_avg is not None else {},
                    )
                )
                resources.append(resource)
    return resources


def scan_ebs_volumes(db: Session, region: str) -> list[Resource]:
    ec2 = boto3.client("ec2", region_name=region)
    resources: list[Resource] = []

    paginator = ec2.get_paginator("describe_volumes")
    for page in paginator.paginate():
        for volume in page["Volumes"]:
            volume_id = volume["VolumeId"]
            state = volume["State"]
            resource = _upsert_resource(db, ResourceType.ebs_volume, volume_id, region, volume)

            db.add(
                ResourceSnapshot(
                    resource_id=resource.id,
                    scanned_at=datetime.now(timezone.utc),
                    state=state,
                    metric_snapshot={},
                )
            )
            resources.append(resource)
    return resources


def _get_ec2_avg_cpu(cloudwatch, instance_id: str, lookback_hours: int = 24) -> float | None:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=lookback_hours)
    response = cloudwatch.get_metric_statistics(
        Namespace="AWS/EC2",
        MetricName="CPUUtilization",
        Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
        StartTime=start,
        EndTime=end,
        Period=3600,
        Statistics=["Average"],
    )
    datapoints = response.get("Datapoints", [])
    if not datapoints:
        return None
    return sum(dp["Average"] for dp in datapoints) / len(datapoints)


def _has_active_flag(db: Session, resource_id, rule_type: str) -> bool:
    return (
        db.query(Flag)
        .filter(Flag.resource_id == resource_id, Flag.rule_type == rule_type, Flag.resolved_at.is_(None))
        .first()
        is not None
    )


def detect_idle_ec2(db: Session, resource: Resource) -> Flag | None:
    """Flag EC2 instances running >24h with average CPU below 5%."""
    if resource.resource_type != ResourceType.ec2:
        return None
    if _has_active_flag(db, resource.id, "idle_ec2"):
        return None

    running_since = resource.first_seen_at
    if datetime.now(timezone.utc) - running_since < timedelta(hours=IDLE_EC2_MIN_RUNNING_HOURS):
        return None

    recent_snapshots = (
        db.query(ResourceSnapshot)
        .filter(ResourceSnapshot.resource_id == resource.id, ResourceSnapshot.state == "running")
        .order_by(ResourceSnapshot.scanned_at.desc())
        .limit(24)
        .all()
    )
    cpu_values = [s.metric_snapshot["cpu_avg"] for s in recent_snapshots if s.metric_snapshot.get("cpu_avg") is not None]
    if not cpu_values:
        return None

    avg_cpu = sum(cpu_values) / len(cpu_values)
    if avg_cpu >= IDLE_EC2_CPU_THRESHOLD:
        return None

    flag = Flag(
        resource_id=resource.id,
        rule_type="idle_ec2",
        severity=Severity.medium,
        detected_at=datetime.now(timezone.utc),
    )
    db.add(flag)
    return flag


def detect_unattached_ebs(db: Session, resource: Resource) -> Flag | None:
    """Flag EBS volumes in 'available' state for more than 1 hour."""
    if resource.resource_type != ResourceType.ebs_volume:
        return None
    if _has_active_flag(db, resource.id, "unattached_ebs"):
        return None

    first_available_snapshot = (
        db.query(ResourceSnapshot)
        .filter(ResourceSnapshot.resource_id == resource.id, ResourceSnapshot.state == "available")
        .order_by(ResourceSnapshot.scanned_at.asc())
        .first()
    )
    if first_available_snapshot is None:
        return None

    if datetime.now(timezone.utc) - first_available_snapshot.scanned_at < timedelta(hours=UNATTACHED_EBS_MIN_HOURS):
        return None

    flag = Flag(
        resource_id=resource.id,
        rule_type="unattached_ebs",
        severity=Severity.low,
        detected_at=datetime.now(timezone.utc),
    )
    db.add(flag)
    return flag


def run_scan(db: Session, region: str) -> None:
    """Scan EC2 + EBS in a region, record snapshots, and apply detection rules."""
    ec2_resources = scan_ec2_instances(db, region)
    ebs_resources = scan_ebs_volumes(db, region)

    for resource in ec2_resources:
        detect_idle_ec2(db, resource)
    for resource in ebs_resources:
        detect_unattached_ebs(db, resource)

    db.commit()
