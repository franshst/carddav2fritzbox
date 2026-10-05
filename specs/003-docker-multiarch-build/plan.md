# Implementation Plan: Docker Multi-Architecture Build

**Branch**: `003-docker-multiarch-build` | **Date**: 2026-08-30 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-docker-multiarch-build/spec.md` — extend the `002-docker-swarm-deployment` Docker deliverables so `docker/Dockerfile` builds and runs on both `linux/amd64` and `linux/arm64`. Starting point per user input: a working Docker Swarm cluster with heterogeneous nodes (amd64 + arm64). Evolved per 2026-08-30 user updates: separate `docker/build.sh` (distinct from `docker/deploy.sh`, `deploy.sh` deploy-only) + `SYNC_IMAGE` via `build.sh --push` manifest.

## Summary

Make the existing `docker/Dockerfile` (Alpine-based, stdlib-only wrapper) reliably buildable and runnable on both Swarm node architectures. No application code change is needed — pure-Python sync plus Alpine's dual-arch `python:3.13-alpine` base already supports both platforms. The work is: (1) verify the Dockerfile avoids arch-specific assumptions, (2) provide a **separate build script `docker/build.sh`** (distinct from `docker/deploy.sh`) that encapsulates native and cross-build (`buildx` + QEMU) commands producing a correct multi-arch manifest, (3) ensure the Swarm stack pulls the right variant per node via a registry-published manifest list (or per-node local build), and (4) update `docker/docker.md` + `docker/swarm.md` to reference the new build script and state supported platforms and verification steps. Deliverable scope is intentionally small — ~4 files touched (new `build.sh` + 2 docs + optional compose comment), no new runtime dependencies. Per user clarification 2026-08-30: build logic MUST live in `docker/build.sh`, not in `deploy.sh`.

## Technical Context

**Language/Version**: Python 3.13 (container base `python:3.13-alpine`; project target `py310+` per `pyproject.toml:3`; wrapper is stdlib-only)

**Primary Dependencies**: `python:3.13-alpine` dual-arch base (verified publishes `linux/amd64` + `linux/arm64`); runtime deps `requests>=2.28`, `vobject>=0.9.6`, `Pillow>=9.0.0` (pure Python / musllinux wheels); build tooling `docker buildx` + QEMU emulation for cross-builds encapsulated in new `docker/build.sh` (separation of concerns per user update: build vs deploy); scheduler `crazymax/swarm-cronjob` unchanged; Swarm configs/secrets unchanged (`docker/deploy.sh` remains deploy-only)

**Storage**: None new. Image distribution via registry manifest list / OCI index for heterogeneous Swarm; config via Swarm configs, credentials via Swarm secrets (as in 002). No filesystem or DB state.

**Testing**: Native-build via `docker/build.sh` default (wraps `docker build -f docker/Dockerfile .`), cross-build via `docker/build.sh --push` (wraps `docker buildx build --platform linux/amd64,linux/arm64 --push`) then `docker buildx imagetools inspect` / `docker manifest inspect`, smoke run (`docker run --rm` with mounted config/secret stubs) checking exit-code parity; CI step calls `build.sh` and inspects manifest contains both `linux/amd64` + `linux/arm64`. Existing wrapper pytest suite unchanged. Script separation verified: `deploy.sh` contains no build logic.

**Target Platform**: Linux containers on Docker Swarm with mixed `amd64` + `arm64` worker/manager nodes; one-shot task per `swarm-cronjob` trigger. Registry must be reachable from every node that may schedule the task.

**Project Type**: Container image / DevOps build & deployment documentation (no new service code)

**Performance Goals**: Build correctness over speed — cross-build may be slower under QEMU but must succeed; scheduled sync runtime unchanged (<5 min for typical contact set per 001 `SC-001`); notification email within 5 min of failure per 002 `SC-003`

**Constraints**: Minimal Dependencies (constitution III) — no new runtime packages in image (Pillow musllinux wheels, compiler-free default; `apk add gcc` fallback documented as out-of-scope contingency per research §2 — not implemented); Public APIs Only — only Docker/Swarm public primitives; Secure Credential Management — no secrets in image/logs/stack file; Dockerfile must not pin `--platform=linux/amd64`; `docker/build.sh` vs `docker/deploy.sh` separation (no build in deploy)

**Scale/Scope**: ~1 Dockerfile verified unchanged (or minimally tweaked), 1 new build script (`docker/build.sh`), 2 docs updated (`docker/docker.md`, `docker/swarm.md`), 1 existing deploy script trimmed to deploy-only (`docker/deploy.sh`), optionally `docker/docker-compose.yml` comment and CI snippet; ~5–6 files touched total

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Clean Code (Pythonic, PEP 8)**: PASS — no new Python code expected; doc/CI changes follow existing style; if a fallback `apk` build stage is needed it stays within PEP 8 wrapper context
- **II. Simple CLI Interface**: PASS — no new CLI surface; build commands are documented shell invocations for operators, not application CLI
- **III. Minimal Dependencies**: PASS — zero new runtime dependencies in image (still `requests`, `vobject`, `Pillow` only). Buildx/QEMU are host/CI build-time tools, not image layers
- **IV. Public APIs Only**: PASS — uses public Docker primitives (`buildx`, manifest list / OCI index, Swarm scheduling, `python:alpine` public image)
- **V. Secure Credential Management**: PASS — unchanged from 002; secrets remain Swarm secrets, not baked into image or visible in docs
- **VI. Modern Python Standards**: PASS — Python 3.13, no deprecated constructs; Alpine image stays on modern tag

Post-design re-check (Phase 1): still PASS — contracts add no runtime deps or private APIs; swarm heterogeneous scheduling relies on standard Swarm image-pull-by-manifest behavior.

## Project Structure

### Documentation (this feature)

```text
specs/003-docker-multiarch-build/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── checklists/
│   └── requirements.md  # Spec quality checklist (from /speckit.specify)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   ├── image-manifest.md  # Manifest list / platform selection contract
│   └── build-commands.md  # Native + cross-build command contract
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
docker/
├── Dockerfile                 # Verified dual-arch; no --platform pin; still python:3.13-alpine
├── build.sh                   # NEW: separate build script (native + --platform/--push cross-build); no secret/stack logic
├── deploy.sh                  # Trimmed to deploy-only: create secrets + `docker stack deploy` (no build)
├── docker-compose.yml         # Unchanged semantics; doc comment about SYNC_IMAGE needing a multi-arch reference
├── docker.md                  # Updated: supported platforms + reference to build.sh (native vs cross modes)
├── swarm.md                   # Updated: multi-node registry requirement + build.sh usage + verification via manifest inspect
├── entrypoint.py              # Unchanged (arch-agnostic, already pure Python)
└── notify.py                  # Unchanged

# Optional CI example (if repo adds CI):
.github/workflows/
└── docker-multiarch.yml       # Calls docker/build.sh --push + manifest inspect (illustrative, not required)

src/                          # Unchanged
tests/                        # Existing wrapper tests unchanged
```

**Structure Decision**: Single-project layout preserved — deliverables stay in the existing `docker/` directory from 002. Separation of concerns per user update: **build** (`docker/build.sh`) vs **deploy** (`docker/deploy.sh`) are distinct scripts. Swarm's existing heterogeneous scheduling (pull correct manifest variant per node) needs no compose change — the image reference must simply point at a multi-arch manifest when nodes are mixed. The build script is the single source of truth for all `docker build`/`buildx` invocations; docs reference it rather than duplicating raw commands.

## Complexity Tracking

> No constitution violations — nothing to justify.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
