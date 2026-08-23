# Data Model: Docker Swarm Deployment

**Feature**: 002-docker-swarm-deployment | **Date**: 2026-08-22

Entities from spec.md §Key Entities, elaborated. No persistent storage is
introduced; these are deployment-time artifacts and runtime records.

## 1. Deployment Stack Definition

The single artifact an operator deploys (`docker/docker-compose.yml`).

| Field | Kind | Validation / Rule |
|-------|------|-------------------|
| service `carddav2fritzbox` | one-shot service | image built from `docker/Dockerfile`; label `swarm.cronjob.enable=true` |
| schedule expression | cron string (label `swarm.cronjob.schedule`) | default nightly; overridable via stack env (SC-005) |
| config mount | read-only bind mount | non-secret `config.ini`, no embedded credentials (FR-008) |
| secret references | list of secret names | every name must exist in the cluster Secret Set before deploy (FR-014) |
| swarm-cronjob service | sidecar | mounts `/var/run/docker.sock`; TZ configurable |

Relationships: references Secret Set by name; instantiates Run Output Record
per trigger.

State: deployed → updated (redeploy) → removed.

## 2. Secret Set

Named cluster-level secrets, one per credential input (contracts/env-secrets.md
is normative for names).

| Entity | Secret name(s) | Maps to env override |
|--------|----------------|----------------------|
| FritzBox password | `fritzbox_password` | `FRITZBOX_PASSWORD` |
| CardDAV source password n | `carddav_<n>_password` (n = priority) | `CARDDAV_<n>_PASSWORD` |
| FTP password (optional) | `ftp_password` | `FTP_PASSWORD` |
| SMTP password (optional) | `smtp_password` | `SMTP_PASSWORD` |

Validation rules:

- Every secret referenced by the stack MUST exist at deploy time; a missing
  file under `/run/secrets/` at run start → fail fast with actionable message
  naming the missing item (FR-014).
- Secret values MUST NOT be logged or echoed (FR-013).

## 3. Wrapper Configuration

Mail/transport settings consumed only by the wrapper (not by the sync).

| Field | Source | Rule |
|-------|--------|------|
| SMTP host | env `SMTP_HOST` | required for notification; absence disables email with startup warning logged |
| SMTP port | env `SMTP_PORT` | default `587` |
| STARTTLS | env `SMTP_STARTTLS` | default `true` |
| SMTP username | env `SMTP_USERNAME` | optional |
| SMTP password | secret `smtp_password` → env `SMTP_PASSWORD` | optional; never logged (FR-013) |
| Sender address | env `EMAIL_FROM` | required when notifications enabled |
| Recipient address | env `EMAIL_TO` | required when notifications enabled |

## 4. Run Output Record

Captured result of one sync execution (in-memory + platform logs).

| Field | Type | Rule |
|-------|------|------|
| stdout+stderr stream | merged text buffer | teed to container logs and retained in memory for the failure email |
| exit code | int 0–4 (existing CLI codes) | container process exits with this code verbatim (research.md §6) |
| outcome | `success` \| `failure` | failure ⇔ exit code ≠ 0 (FR-002) |

Transitions: `scheduled → running → success` (no email) or
`scheduled → running → failure → notify-attempted` (email sent, delivery error
logged if transport fails; exit code unchanged — FR-015).

## 5. Deliverable Files

| File | Purpose |
|------|---------|
| `docker/Dockerfile` | Alpine-based image definition |
| `docker/entrypoint.py` | secret→env mapping + subprocess orchestration |
| `docker/notify.py` | stdlib SMTP failure-email sender |
| `docker/docker-compose.yml` | Swarm stack definition |
| `docker/deploy.sh` | example: create secrets + deploy stack |
| `docker/docker.md` | plain-Docker usage doc |
| `docker/swarm.md` | Swarm deployment/scheduling doc |
