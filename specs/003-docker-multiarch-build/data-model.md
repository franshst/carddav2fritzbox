# Data Model: Docker Multi-Architecture Build

**Feature**: 003-docker-multiarch-build | **Date**: 2026-08-30 | **Spec**: [spec.md](spec.md)

This feature adds no application domain entities (contacts, credentials). Its entities are build/distribution artifacts that extend `002-docker-swarm-deployment`.

## Entity 1: Container Image Variant

**Description**: A runnable build artifact produced from `docker/Dockerfile` for a single platform.

| Attribute | Type | Required | Validation | Notes |
|-----------|------|----------|------------|-------|
| `platform` | enum `linux/amd64` \| `linux/arm64` | Yes | MUST be one of the two supported platforms; no other arch in scope | Declared in manifest `platform` field |
| `base_image` | string | Yes | MUST be `python:3.13-alpine` (or successor) with matching platform manifest | FR-004: no pinned `--platform` in Dockerfile |
| `digest` | string (sha256) | Yes when published | Valid OCI digest | Unique per platform |
| `dependencies` | set[str] | Yes | `requests`, `vobject`, `Pillow` all importable and functional on the variant | FR-005 |
| `entrypoint_contract` | enum | Yes | Same as 002: `python3 /app/docker/entrypoint.py` with secret→env mapping | FR-003, FR-010: behavior identical across variants |

**Relationships**: Zero-to-many `Container Image Variant` belong to one `Multi-Arch Manifest`. One `Container Image Variant` satisfies the `Build Script (docker/build.sh)` target.

**Lifecycle**: Created by `docker build` (native) or `docker buildx build --platform` (cross); content-addressed by digest.

**Invariants**:
- `Dockerfile` is platform-agnostic (no arch-conditional logic, FR-004)
- Two variants from same commit MUST be functionally identical per sync semantics (FR-003, SC-003)

## Entity 2: Multi-Arch Manifest (Manifest List / OCI Index)

**Description**: A single registry reference that resolves to multiple `Container Image Variant`s by platform negotiation.

| Attribute | Type | Required | Validation | Notes |
|-----------|------|----------|------------|-------|
| `reference` | string | Yes | Valid registry reference e.g. `ghcr.io/org/carddav2fritzbox:1.0` | What operators set as `SYNC_IMAGE` in mixed Swarm |
| `manifests[]` | list of {platform, digest, mediaType} | Yes | length == 2; entries for `linux/amd64` and `linux/arm64`, each digest matches a `Container Image Variant` | FR-006, FR-008 |
| `mediaType` | string | Yes | OCI image index or Docker manifest list | Auto-set by buildx |

**Relationships**: References exactly 2 `Container Image Variant`s (amd64 + arm64). No other arch in scope.

**Lifecycle**: Created and pushed by `docker buildx build --push` (or fallback `docker manifest create --amend`). Inspected via `docker buildx imagetools inspect <ref>`.

**Behavior**: `docker pull <reference>` on any Swarm node automatically selects the entry matching the node's `platform.architecture`.

**Invariants**:
- `manifests` MUST contain both required platforms; missing one is a build failure per SC-002
- Stack deployments in mixed Swarm MUST use a manifest reference, not a single-arch local tag (documented in `swarm.md`)

## Entity 3: Build Script (`docker/build.sh`) + Build Instruction

**Description**: The executable shell script `docker/build.sh` that is the **single source of truth** for producing `Container Image Variant`(s) / `Multi-Arch Manifest`. It is **separate** from `docker/deploy.sh` per user update 2026-08-30. The legacy notion of a loose "Build Instruction" is now a script invocation; docs reference the script rather than duplicating raw `docker build` strings.

| Attribute | Type | Required | Validation | Notes |
|-----------|------|----------|------------|-------|
| `path` | string | Yes | MUST be `docker/build.sh` at repo root | Separation from `docker/deploy.sh` |
| `kind` | enum `native` \| `cross` | Yes | Native: single arch build for current host; Cross: `--platform linux/amd64,linux/arm64` via `buildx` | Selected by CLI flags |
| `command` | string | Yes | MUST match `contracts/build-commands.md` invocation forms verbatim (see contract) | FR-007 |
| `requires_tooling` | string[] | Yes | Native: Docker Engine; Cross: Docker Engine + `buildx` + QEMU binfmt (`tonistiigi/binfmt`/`docker/setup-qemu-action`) | |
| `result` | enum | Yes | Native → local image `carddav2fritzbox:local` (or `-t` tag); Cross (`--push`) → pushed `Multi-Arch Manifest` | |

**Script interface contract**:

```
docker/build.sh                          # native build, tag carddav2fritzbox:local
docker/build.sh -t <registry>/…:<tag>    # native build with custom tag
docker/build.sh --push -t <registry>/…:<tag>  # cross build linux/amd64,linux/arm64 and push manifest list
docker/build.sh --help                   # usage
```

**Relationships**: Produces 1 (`native`) or 1 manifest containing 2 (`cross`) `Container Image Variant`s. Owned by `docker/`; no coupling to `deploy.sh`.

**Validation Rules**:
- Script MUST be executable (`chmod +x docker/build.sh`) and located in `docker/` alongside `deploy.sh`
- `deploy.sh` MUST contain no `docker build` / `buildx` invocations (grepped)
- `docker/docker.md` §1 and `docker/swarm.md` §1 MUST reference `build.sh`, not duplicate raw build strings as primary instruction
- `NEEDS CLARIFICATION` never needed — exact invocations are prescribed in contract

## Entity 4: Deployment Script (`docker/deploy.sh`) — deploy-only

Inherited from `002-docker-swarm-deployment/data-model.md`. Clarified per separation: `deploy.sh` is **deploy-only** — it creates/updates Swarm secrets and runs `docker stack deploy`. It MUST NOT build images. The `image` field in the stack (`SYNC_IMAGE`) MUST resolve via the `Multi-Arch Manifest` produced by `build.sh` when the Swarm is heterogeneous (amd64+arm64). No schema change — only operational guidance that `SYNC_IMAGE` point at the `build.sh`-pushed manifest reference and that the registry be reachable from all nodes.

| Attribute | Type | Required | Validation |
|-----------|------|----------|------------|
| `build_contains` | string | Yes | MUST NOT contain `docker build` or `buildx` |
| `deploy_contains` | string | Yes | MUST contain secret creation + `docker stack deploy` |

## Entity 5: Documentation Coverage (derived)

| Attribute | Type | Required | Validation |
|-----------|------|----------|------------|
| `supported_platforms` | list[string] | Yes | MUST equal `[linux/amd64, linux/arm64]` and appear in `docker/docker.md` + `docker/swarm.md` |
| `verification_steps` | list[string] | Yes | MUST include native build, cross-build, and `imagetools inspect` / `manifest inspect` check |

## State Transitions

No application state machine; build artifact flow:

```
source commit → docker/build.sh (native) → Container Image Variant (single arch, local)
                          ↘ docker/build.sh --push → Multi-Arch Manifest (2 variants, pushed) → `deploy.sh` references SYNC_IMAGE → Swarm nodes pull matching variant
deploy.sh never builds; it only deploys secrets + stack that points at the build.sh-produced reference.
```

## Validation Summary (from FRs)

- Every `Container Image Variant` must pass `docker build` on its platform (FR-001, FR-002 → SC-001)
- Cross variant must be producible from single host (FR-006, FR-009 → SC-002)
- Variants must be runtime-equivalent under same inputs (FR-003 → SC-003)
- Manifest must correctly declare platforms (FR-008)
- No regression of 002 invariants (FR-010 → SC-005)
