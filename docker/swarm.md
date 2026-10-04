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
- A sample environment file `docker/.env.example` listing every variable
  consumed by `docker/docker-compose.yml` and `docker/deploy.sh`
  (`SYNC_IMAGE`, `SYNC_CRON`, `TIMEZONE`, `SYNC_CONFIG_PATH`,
  `SYNC_EXPECTED_SECRETS`, `STACK_NAME`, `SMTP_HOST`, `SMTP_PORT`,
  `SMTP_STARTTLS`, `SMTP_USERNAME`, `EMAIL_FROM`, `EMAIL_TO`) — copy it to
  `docker/.env` (or project-root `.env`) and edit (see §3–§5).
  Secrets (`FRITZBOX_PASSWORD`, `CARDDAV_*_PASSWORD`, `SMTP_PASSWORD`,
  `FTP_PASSWORD`) are never placed in `.env`; see
  `specs/002-docker-swarm-deployment/contracts/env-secrets.md` for the
  secret vs plain-env distinction. The real `.env` is git-ignored (`.gitignore`
  `.env*`).

## 1. Build or obtain the image

Build separately via `docker/build.sh` (see `specs/003-docker-multiarch-build`):
```bash
docker/build.sh                                          # native, tag carddav2fritzbox:local (single-host)
docker/build.sh --push -t <registry>/carddav2fritzbox:<tag>  # cross linux/amd64,linux/arm64 and push manifest list
# Verify: docker buildx imagetools inspect <registry>/carddav2fritzbox:<tag>  # expect linux/amd64 + linux/arm64
# multi-node heterogeneous Swarm (amd64+arm64 nodes): SYNC_IMAGE must be the pushed manifest reference above
```
Raw form (what the script wraps): `docker build -f docker/Dockerfile -t carddav2fritzbox:local .`

> `deploy.sh` (§3) does not build — it expects the image already exists (built via `build.sh`) and deploys it via `SYNC_IMAGE`.

## 2. Prepare the configuration file

Create `config.ini` per the main README with **no embedded passwords**.
The stack ships it as a Swarm *config* (`SYNC_CONFIG_PATH` at deploy time),
so the cluster distributes it to every node itself — no bind mounts, works
across multiple managers.

## 3. Create the secrets and deploy — `deploy.sh`

> **Configure via `.env` (optional)**: all stack settings from
> `docker/.env.example` can be kept in `docker/.env` / `.env` instead of
> inline `VAR=...` on the command line. Compose interpolates `${VAR:-default}`
> from the `.env` file automatically, and `deploy.sh` inherits the same
> environment. Example:
> ```bash
> cp docker/.env.example docker/.env   # edit values, then:
> # docker/.env is read automatically by `docker compose` / `docker stack deploy`
> ./deploy.sh                          # uses SYNC_IMAGE, SYNC_CRON, SMTP_*, etc. from .env
> # or with an explicit file: set -a; source docker/.env; set +a; ./deploy.sh
> ```
> See `docker/.env.example` for annotated defaults and the
> `specs/002-docker-swarm-deployment/contracts/env-secrets.md` note that
> credentials never belong in `.env`.

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
enough, no image rebuild. Variables may also be set in `docker/.env` (see
`docker/.env.example`):

```bash
SYNC_CRON="30 4 * * *" ./deploy.sh        # 04:30 daily
TIMEZONE="Europe/Berlin" SYNC_CRON="0 */6 * * *" ./deploy.sh   # every 6h
# equivalent via .env: set SYNC_CRON/TIMEZONE in docker/.env then ./deploy.sh
```

Overlapping triggers are skipped while a run is still active; missed runs
are skipped rather than queued.

## 5. Failure notifications

Set these when deploying (they flow into the container environment); you
may also persist them in `docker/.env` per `docker/.env.example` instead of
inline assignment:

```bash
SMTP_HOST=smtp.example.com SMTP_PORT=587 SMTP_STARTTLS=true \
SMTP_USERNAME=mailer EMAIL_FROM=sync@example.com EMAIL_TO=admin@example.com \
./deploy.sh
# or: edit docker/.env (SMTP_HOST, SMTP_PORT, SMTP_STARTTLS, SMTP_USERNAME,
# EMAIL_FROM, EMAIL_TO) then ./deploy.sh
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
| "No such image" / `no matching manifest` (heterogeneous Swarm) | push a multi-arch manifest via `docker/build.sh --push -t <registry>:<tag>` and set `SYNC_IMAGE=<registry>:<tag>`; verify with `docker buildx imagetools inspect <registry>:<tag>` (expect `linux/amd64` + `linux/arm64`) |
| Config error about missing option | config.ini lacks a key, or an expected secret was skipped |
| No email despite failures | `SMTP_HOST`/`EMAIL_FROM`/`EMAIL_TO` unset, wrong, or unreachable — check logs for the delivery error line |

## 7. Removing the stack

```bash
docker stack rm carddav2fritzbox
docker config rm carddav2fritzbox_sync_config   # if left behind
```

Secrets are intentionally kept; remove them explicitly if desired.
