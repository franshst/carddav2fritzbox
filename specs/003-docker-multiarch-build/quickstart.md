# Quickstart: Verify Docker Multi-Architecture Build

**Feature**: 003-docker-multiarch-build | **Date**: 2026-08-30 | **Spec**: [spec.md](spec.md)

This guide validates SC-001–SC-005 without requiring two physical machines at once (FR-009). It starts from a working Swarm with mixed amd64 + arm64 nodes. Build logic lives in **`docker/build.sh`** (separate from `docker/deploy.sh` per user update 2026-08-30).

## Prerequisites

- Docker Engine ≥ 20.10 with `buildx` (bundled in current Docker Desktop / Engine)
- A Swarm already initialized (`docker swarm init` / joined nodes); at least one amd64 and one arm64 node visible via `docker node ls`
- A registry reachable from every Swarm node (e.g., `ghcr.io/<org>` or `registry.example.com`) — needed for mixed Swarm deploys (Swarm pulls per-node). For plain single-host checks, no registry is needed.
- `config.ini` with non-secret settings and at least one CardDAV source + FritzBox address book configured (no passwords inside — they come via secrets)

## 1. Native build on current host via build script (SC-001)

From repository root:

```bash
chmod +x docker/build.sh
docker/build.sh
docker run --rm carddav2fritzbox:local --help   # wrapper prints help and exits 0 without secrets

# Custom tag:
docker/build.sh -t myregistry/carddav2fritzbox:test

# smoke with secrets (use deploy.sh or mount stub secrets):
printf '%s' dummy > /tmp/fb_secret
docker run --rm \
  -v "$PWD/config.ini:/config/config.ini:ro" \
  -v /tmp/fb_secret:/run/secrets/fritzbox_password:ro \
  -e SYNC_EXPECTED_SECRETS=fritzbox_password \
  carddav2fritzbox:local
rm /tmp/fb_secret
echo "exit code: $?"  # expect 2 (missing real CardDAV creds) or 0 if mocked — but no image error
```

Verify separation:

```bash
./docker/build.sh --help
! grep -q "docker build" docker/deploy.sh && echo "PASS: deploy.sh is deploy-only"
```

Repeat on the opposite architecture if you have access to both hosts; otherwise the cross-build step covers the other arch.

## 2. Cross-build both platforms from one host via build script (SC-002)

```bash
# One-time setup (if not already done):
docker buildx create --use --name multi  # skip if a builder already exists
docker run --privileged --rm tonistiigi/binfmt --install all   # QEMU binfmt; or use docker/setup-qemu-action in CI

# Build and push the multi-arch manifest via the build script (replace <registry>/<tag>):
REGISTRY=ghcr.io/<org>/carddav2fritzbox
TAG=test-multiarch
docker/build.sh --push -t "$REGISTRY:$TAG"
# Equivalent to:
# docker buildx build --platform linux/amd64,linux/arm64 -t "$REGISTRY:$TAG" -f docker/Dockerfile --push .
```

Verify (no arm64 host needed):

```bash
docker buildx imagetools inspect "$REGISTRY:$TAG"
# Expect two entries, e.g.:
#   Name: ghcr.io/<org>/carddav2fritzbox:test-multiarch@sha256:…  Platform: linux/amd64
#   Name: ghcr.io/<org>/carddav2fritzbox:test-multiarch@sha256:…  Platform: linux/arm64

# Older Docker alternative:
docker manifest inspect "$REGISTRY:$TAG" | grep -E 'architecture|os'
# Expect architecture: amd64 and arm64, os: linux
```

## 3. Functional parity smoke (SC-003)

With a mocked or real CardDAV + FritzBox endpoint (existing 002 quickstart fixtures), run the native image and, if available, pull the opposite arch variant and run it (or run under emulation):

```bash
# Native (built via build.sh):
docker run --rm \
  -v "$PWD/config.ini:/config/config.ini:ro" \
  -v /tmp/fb_secret:/run/secrets/fritzbox_password:ro \
  -e SYNC_EXPECTED_SECRETS=fritzbox_password \
  carddav2fritzbox:local

# Cross-built (pull by digest for the explicit other arch):
docker pull --platform linux/arm64 "$REGISTRY:$TAG"   # on an amd64 host under emulation, or natively on arm64
docker run --rm --platform linux/arm64 \
  -v "$PWD/config.ini:/config/config.ini:ro" \
  -v /tmp/fb_secret:/run/secrets/fritzbox_password:ro \
  -e SYNC_EXPECTED_SECRETS=fritzbox_password \
  "$REGISTRY:$TAG"
# Compare: both runs must produce the same exit code and, against the same mocks, the same phonebook result.
```

## 4. Mixed Swarm deployment (SC-005 — no regression)

```bash
# Ensure the multi-arch image is reachable from all Swarm nodes (SC-002 already pushed it via build.sh)
SYNC_IMAGE="$REGISTRY:$TAG" ./docker/deploy.sh  # deploy.sh creates secrets + deploys stack (no build)
# or explicitly:
SYNC_IMAGE="$REGISTRY:$TAG" docker stack deploy -c docker/docker-compose.yml carddav2fritzbox

# Observe which nodes pull which variant:
docker service ps --format '{{.Node}} {{.CurrentState}}' carddav2fritzbox_carddav2fritzbox
docker service logs carddav2fritzbox_carddav2fritzbox  # full run output (wrapper tee)
# Trigger an on-demand run if you don't want to wait for the cron schedule:
docker service update --force carddav2fritzbox_carddav2fritzbox
```

If a task lands on an `arm64` node and another on `amd64` (after re-scheduling), both must complete with the same semantics as in the single-arch 002 deployment.

## 5. Documentation check (SC-004)

```bash
grep -i "build.sh\|amd64\|arm64\|buildx\|imagetools" docker/docker.md
grep -i "build.sh\|amd64\|arm64\|SYNC_IMAGE\|imagetools" docker/swarm.md
# Each file must mention supported platforms (linux/amd64, linux/arm64) and the build script (docker/build.sh --push)
```

## Expected outcomes

- SC-001: `docker/build.sh` native build succeeds on either arch.
- SC-002: `docker/build.sh --push` produces a manifest with exactly `linux/amd64` + `linux/arm64`.
- SC-003: Same mocked input → same exit code / phonebook on both variants.
- SC-004: Docs mention both platforms and `docker/build.sh`.
- SC-005: Swarm stack (mixed nodes) schedules and runs without `No such image` / `no matching manifest` errors; `deploy.sh` never builds.

## Cleanup

```bash
docker stack rm carddav2fritzbox
docker buildx rm multi  # if created
docker manifest rm "$REGISTRY:$TAG" 2>/dev/null; true
```
