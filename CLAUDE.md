# CloudWatchdog — Project Context

## What this is
A tool that scans an AWS account for "forgotten" resources — things left running,
unattached, or unused that quietly cost money or create security risk — and
surfaces them on a dashboard with rule-based flags.

## Scope for this build (important)
This is a fast, focused build. Explicitly OUT of scope for now:
- Real AWS deployment (Lambda, EventBridge, RDS, cross-account IAM roles) —
  this runs LOCALLY only for now, using Docker Postgres + local FastAPI,
  making real boto3 calls against a personal AWS account.
- IAM temporary credential scanning — skip this resource type entirely for now.
  Only scan: EC2 instances and EBS volumes.
- Authentication/login on the dashboard.
- Email/SNS alerting.

IN scope: FastAPI backend, Postgres via Docker, boto3 scanning of EC2 + EBS,
rule-based flagging, React dashboard to view resources and flags.

## Tech stack
- Backend: FastAPI (Python), SQLAlchemy, Alembic for migrations
- Database: Postgres, running locally via docker-compose
- AWS access: boto3, using local AWS credentials (already configured via AWS CLI
  or environment variables)
- Frontend: React

## Data model

### `resources` table — current known state of each AWS resource
| Column | Type | Notes |
|---|---|---|
| id | UUID, PK | |
| aws_resource_id | string, indexed | AWS's own ID, e.g. i-0abc123 or vol-0abc123 |
| resource_type | enum: `ec2`, `ebs_volume` | |
| region | string | |
| raw_metadata | JSON | Full boto3 response for this resource. Tags are NOT
  extracted into a separate column — they live inside raw_metadata and are
  parsed on read via a helper function, since EC2 and EBS represent tags
  differently in their raw boto3 shape. This was a deliberate choice to avoid
  keeping two sources of truth in sync; revisit only if tag-based querying
  becomes a real bottleneck. |
| first_seen_at | timestamp | |
| last_seen_at | timestamp | Updated every scan that still finds this resource |

### `resource_snapshots` table — one row per scan per resource (history)
| Column | Type | Notes |
|---|---|---|
| id | UUID, PK | |
| resource_id | FK -> resources.id | |
| scanned_at | timestamp | |
| state | string | e.g. `running`, `stopped`, `available`, `in-use` |
| metric_snapshot | JSON | e.g. `{"cpu_avg": 2.1}` for EC2. Shape varies by
  resource_type, hence JSON rather than fixed columns. |

### `flags` table — detected issues
| Column | Type | Notes |
|---|---|---|
| id | UUID, PK | |
| resource_id | FK -> resources.id | |
| rule_type | string | e.g. `idle_ec2`, `unattached_ebs` |
| severity | enum: `low`, `medium`, `high` | |
| detected_at | timestamp | |
| resolved_at | timestamp, nullable | null = still active |
| alerted_at | timestamp, nullable | not used yet (no alerting in this build),
  but keep the column for future use |

Relationships: one `resource` has many `resource_snapshots` and many `flags`,
via `resource_id` foreign keys.

## Detection rules (v1)
- `idle_ec2`: EC2 instance running for more than 24 hours with average CPU
  below 5%, based on recent snapshots.
- `unattached_ebs`: EBS volume in `available` state (i.e. not attached to any
  instance) for more than 1 hour since first observed in that state.
- Both rules should be simple, readable functions — not a generic rule engine.
  Clarity over cleverness for v1.

## API design
```
GET   /health                    -> confirms DB connectivity
GET   /resources                 -> list resources, query params: type, has_flags
GET   /resources/{id}            -> single resource detail
GET   /resources/{id}/snapshots  -> history for one resource
GET   /flags                     -> list flags, query params: severity, active_only
PATCH /flags/{id}                -> manually resolve/acknowledge a flag
```
Deliberate choice: `/resources` and `/flags` are separate endpoints, not joined
server-side. The frontend fetches both and joins in React. This is the simpler
option; only add server-side joining if it becomes a real performance need.

## Why polling, not event-driven (CloudTrail streaming)
Detection here doesn't need real-time latency — "idle for 24 hours" doesn't
need sub-second detection. Polling AWS on a schedule (every 15 min in the real
version; can be manually triggered for this local build) is far simpler to
reason about and debug than consuming a CloudTrail event stream.

## Current status
Fresh repo, nothing built yet. Docker is installed and confirmed working
(`docker run hello-world` succeeded). Next step: docker-compose for Postgres,
then FastAPI scaffolding.
