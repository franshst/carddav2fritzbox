# Contract: Multi-Arch Image Manifest

**Feature**: 003-docker-multiarch-build | **Date**: 2026-08-30

Source: `FR-006`, `FR-008`, `FR-010`; `docker/docker-compose.yml:37` (`SYNC_IMAGE`); starting point is a heterogeneous Swarm (amd64 + arm64 nodes).

## Manifest shape

A single registry reference (OCI image index / Docker manifest list) that Docker's pull logic resolves per-node by platform.

**Reference**: `<registry>/carddav2fritzbox:<tag>` — produced by `docker/build.sh --push` (see `build-commands.md`) and consumed as `SYNC_IMAGE` when deploying to a mixed Swarm:
```bash
docker/build.sh --push -t <registry>/carddav2fritzbox:<tag>
SYNC_IMAGE=<registry>/carddav2fritzbox:<tag> ./docker/deploy.sh
# or
SYNC_IMAGE=<registry>/carddav2fritzbox:<tag> docker stack deploy -c docker/docker-compose.yml carddav2fritzbox
```

**Required entries**: Exactly two manifests, each with:

| Field | Required value |
|-------|----------------|
| `mediaType` | `application/vnd.oci.image.manifest.v1+json` or `application/vnd.docker.distribution.manifest.v2+json` |
| `platform.os` | `linux` |
| `platform.architecture` | `amd64` for one entry, `arm64` for the other |
| `digest` | SHA256 of the image config for that platform |

No `arm/v7`, `ppc64le`, `386`, etc. entries are required (out of scope).

## Swarm behavior

- Swarm scheduler may place the one-shot `carddav2fritzbox` task on any node (subject to constraints). The engine on that node issues `pull <reference>`; when the reference is a manifest list, the engine negotiates and fetches only the matching platform manifest (and layers). No change to `docker-compose.yml` `deploy`/`placement` is needed.
- Local-only tag `carddav2fritzbox:local` (no registry) is **not** a manifest list — it only exists on the node where it was built. Documented as suitable for single-host/standalone use (`docker/docker.md`), not for mixed Swarm. Mixed Swarm MUST use a pushed manifest list or per-node pre-loaded images.

## Verification

```bash
# After pushing via `docker/build.sh --push` (see build-commands.md):
docker buildx imagetools inspect <registry>/carddav2fritzbox:<tag>
docker manifest inspect <registry>/carddav2fritzbox:<tag>  # older Docker

# Expected: two entries, architectures == amd64, arm64; both linux
# On a specific node, confirm which variant was pulled:
docker inspect --format '{{.Os}}/{{.Architecture}}' $(docker ps -q -f name=carddav2fritzbox)
```

## Failure modes

| Condition | Manifest state | Swarm consequence | Fix |
|-----------|---------------|-------------------|-----|
| Only amd64 was pushed | Single manifest, no arm64 entry | Tasks scheduled on arm64 nodes fail with `no matching manifest` / pull error | Re-run cross-build with `--platform linux/amd64,linux/arm64` and push |
| Dockerfile used `--platform=linux/amd64` in FROM | Manifest may still be two entries but the arm64 image's base is wrong, or build failed | arm64 build fails outright | Remove `--platform` pin (FR-004) |
| Registry unreachable from a subset of nodes | Manifest exists but pull fails on those nodes | Task state `Rejected` / `No such image` (see `swarm.md` §6) | Ensure registry reachable / credentials distributed |

## No breaking change to existing 002 contract

- Service definition (`docker/docker-compose.yml:36-76`) unchanged — `image: ${SYNC_IMAGE:-carddav2fritzbox:local}` already parameterized.
- Swarm cron scheduling, secrets, configs, wrapper exit-code semantics remain identical.
- A homogeneous Swarm (all amd64 or all arm64) may keep using either a single-arch push or a manifest list — the manifest list case is a superset that still works on homogeneous clusters.

## Contract test (no second host required)

```bash
REF=<registry>/carddav2fritzbox:<tag>
count=$(docker buildx imagetools inspect "$REF" | grep -c "linux/\(amd64\|arm64\)")
[ "$count" -eq 2 ] || { echo "FAIL: expected 2 platforms, got $count"; exit 1; }
docker buildx imagetools inspect "$REF" | grep -q "linux/amd64"
docker buildx imagetools inspect "$REF" | grep -q "linux/arm64"
echo "PASS: manifest contains both linux/amd64 and linux/arm64"
```
