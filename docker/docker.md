# Running carddav2fritzbox with plain Docker

This document covers one-shot runs of the containerized sync on a single
Docker host — no Swarm required. For scheduled cluster deployment see
[swarm.md](swarm.md).

## 1. Build the image

From the repository root (see `specs/003-docker-multiarch-build`):

- Supported platforms: `linux/amd64` and `linux/arm64` (`docker/Dockerfile` is platform-agnostic, `python:3.13-alpine`)
- Build via the dedicated build script (single source of truth — do not duplicate `docker build` elsewhere):
  ```bash
  docker/build.sh                          # native, tag carddav2fritzbox:local (current host)
  docker/build.sh --push -t <registry>/carddav2fritzbox:<tag>  # cross linux/amd64,linux/arm64 and push manifest list
  ```
  Raw form (what the script wraps): `docker build -f docker/Dockerfile -t carddav2fritzbox:local .`
  Verify multi-arch (after `--push`): `docker buildx imagetools inspect <registry>/carddav2fritzbox:<tag>` — expect `linux/amd64` + `linux/arm64` (see `specs/003-docker-multiarch-build/contracts/build-commands.md:60`).

The image is Alpine-based, installs only the sync's runtime dependencies
(no dev tools), and runs as a non-root user. `docker/deploy.sh` does not build.

## 2. Prepare configuration

Create a `config.ini` following the main README. Two rules:

- The file must contain **no passwords** — credentials come from
  environment variables or secrets (next section).
- Mount it read-only at `/config/config.ini`, or set `SYNC_CONFIG` to
  another in-container path.

## 3. Provide credentials

The sync accepts the documented environment-variable overrides (see README,
"Environment Variables"). For quick local tests you may pass them directly:

```bash
docker run --rm \
  -v "$PWD/config.ini:/config/config.ini:ro" \
  -e FRITZBOX_PASSWORD='…' \
  -e CARDDAV_1_PASSWORD='…' \
  carddav2fritzbox:local
```

For better hygiene without a cluster, bind-mount files into the wrapper's
secret directory yourself (same mapping as the Swarm deployment):

```bash
printf '%s' '…' > /tmp/fb_secret.txt    # protect this file, delete after use
docker run --rm \
  -v "$PWD/config.ini:/config/config.ini:ro" \
  -v /tmp/fb_secret.txt:/run/secrets/fritzbox_password:ro \
  -e SYNC_EXPECTED_SECRETS=fritzbox_password \
  carddav2fritzbox:local
rm /tmp/fb_secret.txt
```

Note: real Docker secrets only work for Swarm *services*, not plain
`docker run`; the bind-mount above emulates them locally.

Supported secret names (files under `/run/secrets/`):

| Secret | Becomes |
|--------|---------|
| `fritzbox_password` | `FRITZBOX_PASSWORD` |
| `carddav_<n>_password` | `CARDDAV_<n>_PASSWORD` |
| `ftp_password` | `FTP_PASSWORD` — **not needed by default**: FTP reuses the FritzBox web credentials |
| `smtp_password` | `SMTP_PASSWORD` |

## 4. Failure email (optional)

Set these to receive one email whenever a run exits non-zero; successful
runs never send mail.

```bash
docker run --rm --network host \
  -v "$PWD/config.ini:/config/config.ini:ro" \
  -e SMTP_HOST=smtp.example.com \
  -e SMTP_PORT=587 \
  -e SMTP_STARTTLS=true \
  -e SMTP_USERNAME=mailer            # optional
  -e EMAIL_FROM=sync@example.com \
  -e EMAIL_TO=admin@example.com \
  carddav2fritzbox:local
```

- `SMTP_STARTTLS=false` for servers without STARTTLS.
- With `SMTP_USERNAME` set, provide `smtp_password` as a secret.
- If delivery fails, the error is logged but the run's exit code is
  unchanged.

## 5. Exit codes

The container exits with the sync's own exit code:

| Code | Meaning |
|------|---------|
| 0 | success |
| 2 | configuration / missing-secret error (before any network contact) |
| other non-zero | runtime failure — check output; if mail settings are complete, it was emailed |

## 6. Notes

- Runs are non-interactive and stateless; schedule them with your own
  cron/scheduler or switch to the Swarm stack for built-in scheduling.
- Overlapping runs are not queued; a still-running job simply occupies the
  container until finished.
