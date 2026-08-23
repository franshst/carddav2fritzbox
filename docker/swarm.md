# Deploying carddav2fritzbox as a Docker Swarm stack

This document covers scheduled, hands-off deployment in a Docker Swarm
cluster. For one-shot runs on a single host see [docker.md](docker.md).

## Prerequisites

- A Docker Swarm cluster (`docker swarm init` / joined workers)
- `crazymax/swarm-cronjob` — included in the stack file as a sidecar service;
  it needs the manager's Docker socket (mounted read-only) and must run on a
  manager node (constraint already set)
- The image reachable by **every node** that may run the sync: push it to a
  registry and override `SYNC_IMAGE`, e.g.
  `SYNC_IMAGE=registry.example.com/carddav2fritzbox:1.0`
  (a locally built image only exists on the build node!)
- Outbound SMTP access for failure notifications (optional)

## 1. Build or obtain the image

```bash
docker build -f docker/Dockerfile -t carddav2fritzbox:local .
# multi-node clusters: tag & push, then export SYNC_IMAGE accordingly
```

## 2. Prepare the configuration file

Create `config.ini` per the main README with **no embedded passwords**.
The stack ships it as a Swarm *config* (`SYNC_CONFIG_PATH` at deploy time),
so the cluster distributes it to every node itself — no bind mounts, works
across multiple managers.

## 3. Create the secrets and deploy — `deploy.sh`

```bash
cd docker
./deploy.sh                       # interactive prompts per secret
```

or non-interactively:

```bash
./deploy.sh --from-file fritzbox_password=/secure/fb.txt \
            --from-file carddav_1_password=/secure/nc1.txt
```

Secret names are fixed:

| Secret | Required |
|--------|----------|
| `fritzbox_password` | yes |
| `carddav_<n>_password` | one per configured CardDAV source |
| `smtp_password` | only with SMTP authentication |
| `ftp_password` | not needed — FTP reuses the FritzBox web credentials |

Re-running is idempotent; existing secrets are kept unless you confirm
replacement. The script then deploys the stack.

## 4. Schedule

The default schedule is nightly (`0 3 * * *`), expressed as a cron label on
the sync service. Change it via environment at deploy time — a redeploy is
enough, no image rebuild:

```bash
SYNC_CRON="30 4 * * *" ./deploy.sh        # 04:30 daily
TIMEZONE="Europe/Berlin" SYNC_CRON="0 */6 * * *" ./deploy.sh   # every 6h
```

Overlapping triggers are skipped while a run is still active; missed runs
are skipped rather than queued.

## 5. Failure notifications

Set these when deploying (they flow into the container environment):

```bash
SMTP_HOST=smtp.example.com SMTP_PORT=587 SMTP_STARTTLS=true \
SMTP_USERNAME=mailer EMAIL_FROM=sync@example.com EMAIL_TO=admin@example.com \
./deploy.sh
```

On any failed run you receive exactly one email containing the full output
and the exit code; successful runs stay silent. Delivery problems are
logged but never change the run's exit code.

## 6. Verify and troubleshoot

```bash
docker service ls | grep carddav2fritzbox
docker service logs carddav2fritzbox_carddav2fritzbox     # full run output
docker service ps carddav2fritzbox_carddav2fritzbox       # task states
```

| Symptom | Cause / fix |
|---------|-------------|
| Task state `Rejected`: "secret not found" | create the missing secret (§3) |
| Task exits immediately, log names a required secret | wrapper fail-fast (exit 2): secret declared expected but absent |
| "No such image" | push the image to a registry all nodes can pull; set `SYNC_IMAGE` |
| Config error about missing option | config.ini lacks a key, or an expected secret was skipped |
| No email despite failures | `SMTP_HOST`/`EMAIL_FROM`/`EMAIL_TO` unset, wrong, or unreachable — check logs for the delivery error line |

## 7. Removing the stack

```bash
docker stack rm carddav2fritzbox
docker config rm carddav2fritzbox_sync_config   # if left behind
```

Secrets are intentionally kept; remove them explicitly if desired.
