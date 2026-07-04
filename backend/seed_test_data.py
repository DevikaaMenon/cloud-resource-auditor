"""Seed fake resources + snapshots and prove idle_ec2 / unattached_ebs fire end-to-end.

Run from backend/ with the venv active: python seed_test_data.py
Safe to re-run: deletes any prior rows for these fake resource ids first.
"""

import sys
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models import Resource, ResourceSnapshot, ResourceType
from app.scanner import detect_idle_ec2, detect_unattached_ebs

EC2_AWS_ID = "i-0testidle123"
EBS_AWS_ID = "vol-0testorphan456"


def cleanup(db):
    existing = (
        db.query(Resource)
        .filter(Resource.aws_resource_id.in_([EC2_AWS_ID, EBS_AWS_ID]))
        .all()
    )
    for resource in existing:
        db.delete(resource)
    db.commit()


def seed_ec2(db) -> Resource:
    now = datetime.now(timezone.utc)
    resource = Resource(
        aws_resource_id=EC2_AWS_ID,
        resource_type=ResourceType.ec2,
        region="us-east-1",
        raw_metadata={"InstanceId": EC2_AWS_ID, "InstanceType": "t3.micro"},
        first_seen_at=now - timedelta(hours=30),  # running_since, > 24h ago
        last_seen_at=now,
    )
    db.add(resource)
    db.flush()

    db.add(
        ResourceSnapshot(
            resource_id=resource.id,
            scanned_at=now - timedelta(hours=1),
            state="running",
            metric_snapshot={"cpu_avg": 1.8},  # below the 5% threshold
        )
    )
    db.commit()
    db.refresh(resource)
    return resource


def seed_ebs(db) -> Resource:
    now = datetime.now(timezone.utc)
    resource = Resource(
        aws_resource_id=EBS_AWS_ID,
        resource_type=ResourceType.ebs_volume,
        region="us-east-1",
        raw_metadata={"VolumeId": EBS_AWS_ID, "Size": 8},
        first_seen_at=now - timedelta(hours=2),
        last_seen_at=now,
    )
    db.add(resource)
    db.flush()

    db.add(
        ResourceSnapshot(
            resource_id=resource.id,
            scanned_at=now - timedelta(hours=2),  # first seen 'available' > 1h ago
            state="available",
            metric_snapshot={},
        )
    )
    db.commit()
    db.refresh(resource)
    return resource


def print_snapshots(db, resource: Resource, label: str) -> None:
    snapshots = (
        db.query(ResourceSnapshot)
        .filter(ResourceSnapshot.resource_id == resource.id)
        .order_by(ResourceSnapshot.scanned_at.asc())
        .all()
    )
    print(f"    {label} snapshots evaluated by the rule:")
    for s in snapshots:
        print(
            f"      state={s.state!r} scanned_at={s.scanned_at.isoformat()} "
            f"metric_snapshot={s.metric_snapshot}"
        )
    print(f"    {label} first_seen_at={resource.first_seen_at.isoformat()}")


def main() -> int:
    db = SessionLocal()
    try:
        cleanup(db)

        ec2_resource = seed_ec2(db)
        ebs_resource = seed_ebs(db)

        print("Seeded resources:")
        print(f"  EC2  {EC2_AWS_ID}  (id={ec2_resource.id})")
        print(f"  EBS  {EBS_AWS_ID}  (id={ebs_resource.id})")
        print()

        idle_flag = detect_idle_ec2(db, ec2_resource)
        unattached_flag = detect_unattached_ebs(db, ebs_resource)
        db.commit()

        all_passed = True

        print("idle_ec2 (EC2 instance):")
        if idle_flag is not None:
            print(
                f"  PASS - flag created: rule_type={idle_flag.rule_type!r} "
                f"severity={idle_flag.severity.value!r}"
            )
        else:
            all_passed = False
            print("  FAIL - detect_idle_ec2() returned None, no flag created")
            print_snapshots(db, ec2_resource, "EC2")

        print()
        print("unattached_ebs (EBS volume):")
        if unattached_flag is not None:
            print(
                f"  PASS - flag created: rule_type={unattached_flag.rule_type!r} "
                f"severity={unattached_flag.severity.value!r}"
            )
        else:
            all_passed = False
            print("  FAIL - detect_unattached_ebs() returned None, no flag created")
            print_snapshots(db, ebs_resource, "EBS")

        print()
        print("Overall:", "PASS" if all_passed else "FAIL")
        return 0 if all_passed else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
