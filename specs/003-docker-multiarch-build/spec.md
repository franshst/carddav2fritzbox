# Feature Specification: Docker Multi-Architecture Build

**Feature Branch**: `003-docker-multiarch-build`

**Created**: 2026-08-30

**Status**: Draft

**Input**: User description: "add to the specs of the docker deployment that the dockerfile should build on amd64 and arm64."

**Extends**: `002-docker-swarm-deployment` — adds multi-architecture build constraints to the existing Docker/Swarm deliverables in `docker/`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Build and run the image natively on amd64 and arm64 (Priority: P1)

An operator on either an amd64 (x86_64) host (e.g., Intel/AMD NAS, VM, or CI runner) or an arm64 (AArch64) host (e.g., Raspberry Pi 4/5, Apple Silicon, ARM-based NAS) builds the Docker image from the repository's `docker/Dockerfile` and runs the sync container. On both architectures the container starts, executes the sync (or dry-run/help), and produces identical functional results for the same inputs.

**Why this priority**: The core value is hardware portability — the sync's target audience runs home servers on both amd64 and ARM-based devices (notably Raspberry Pi). Without builds on both architectures the deployment feature from 002 is unusable for a large segment of operators.

**Independent Test**: Can be fully tested by building the image on an amd64 machine and on an arm64 machine (or via emulated build) and running the container on each to verify it starts and completes a sync/dry-run successfully.

**Acceptance Scenarios**:

1. **Given** an amd64 host with Docker, **When** the operator builds the image via `docker/build.sh` (native, wraps `docker build -f docker/Dockerfile .`), **Then** the build completes without architecture-specific errors.
2. **Given** an arm64 host with Docker, **When** the operator builds the same `docker/Dockerfile` via `docker/build.sh`, **Then** the build completes without architecture-specific errors.
3. **Given** an image built for the host's architecture (amd64 or arm64) via `docker/build.sh`, **When** the container is run with valid configuration, **Then** it executes the sync and exits with the same semantics (exit codes, FritzBox result) as on the other architecture.
4. **Given** a registry-published multi-arch image (if publishing is used) produced by `docker/build.sh --push`, **When** a user pulls without specifying a platform, **Then** Docker automatically selects the manifest matching the host architecture and the container runs correctly.

---

### User Story 2 - Emulated / cross-build produces both images from a single host (Priority: P2)

A maintainer or CI pipeline building on a single architecture (typically amd64) can produce both amd64 and arm64 images in one build invocation so that both variants are publishable without needing two physical hosts.

**Why this priority**: Enables CI/CD and single-machine publishing; reduces operational friction for releasing.

**Independent Test**: Can be fully tested by running a multi-platform build command on one host and verifying that both `linux/amd64` and `linux/arm64` images/manifests are produced.

**Acceptance Scenarios**:

1. **Given** a single build host with multi-arch tooling available, **When** the maintainer runs `docker/build.sh --push -t <registry>:<tag>` for `linux/amd64` and `linux/arm64`, **Then** both images are produced and runnable on their respective architectures (or verifiable via `docker buildx imagetools inspect`).
2. **Given** a CI workflow, **When** it runs `docker/build.sh --push -t <registry>:<tag>`, **Then** it publishes a multi-arch manifest covering both amd64 and arm64.

---

### User Story 3 - Documentation tells the operator which platform they get (Priority: P3)

An operator reading the Docker documentation can see that the image supports amd64 and arm64, knows how to build for their architecture, and knows how to request a cross-build if needed.

**Why this priority**: Discoverability — without documentation an operator may assume only amd64 is supported.

**Independent Test**: Can be fully tested by a new user following only the Docker documentation to build/run on their (amd64 or arm64) host without consulting other files.

**Acceptance Scenarios**:

1. **Given** the Docker documentation in `docker/`, **When** a user reads it, **Then** it states which architectures are supported and the build commands (`docker/build.sh` native and `docker/build.sh --push`) for operators/maintainers.

---

### Edge Cases

- What happens when the base image `python:3.13-alpine` does not have a variant for one of the target architectures? → Build MUST fail with a clear error; maintainer must choose an alternative base that does support both (stock `python:3.13-alpine` already provides both, so this is a guard case).
- What happens when a Python dependency includes native extensions (e.g., Pillow) that need compilation per architecture? → The Dockerfile must install/build those dependencies in a way that succeeds on both amd64 and arm64 without requiring architecture-specific branches in the Dockerfile.
- What happens when a user tries to run an amd64-only image on arm64 (or vice versa) without emulation? → The runtime error is a platform mismatch; documentation should clarify the need to pull/build the correct architecture variant.
- What happens when emulation (e.g., QEMU) is slow or unavailable on the build host? → Cross-build may be slow but must still produce a correct image; the specification does not mandate a build-time SLA, only correctness.
- What happens when the existing `docker/` deliverables from 002 (entrypoint, notify, Swarm stack) are used unchanged? → They must remain architecture-agnostic (pure Python, no arch-specific paths) and work identically on both platforms.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The `docker/Dockerfile` MUST build successfully on `linux/amd64`.
- **FR-002**: The `docker/Dockerfile` MUST build successfully on `linux/arm64` (AArch64).
- **FR-003**: The runtime behavior of the image (sync execution, entrypoint wrapper, failure-email notification) MUST be functionally identical on amd64 and arm64 for the same inputs and configuration.
- **FR-004**: The Dockerfile MUST NOT contain architecture-specific hard-coding that prevents a build on the other supported architecture (e.g., no `platform`-pinned `FROM --platform=linux/amd64` that blocks arm64 builds).
- **FR-005**: Python dependencies installed in the image (requests, vobject, Pillow and transitive deps) MUST install and function on both amd64 and arm64.
- **FR-006**: When a multi-platform build is performed, the build MUST be able to produce a multi-arch image/manifest that serves `linux/amd64` and `linux/arm64` from a single publishable reference (e.g., Docker manifest list / OCI index) — build tooling documentation MUST describe how to do this.
- **FR-007**: Documentation in `docker/` MUST list the supported architectures (amd64 and arm64) and describe the native-build (`docker/build.sh`) and cross-build (`docker/build.sh --push -t <registry>:<tag>`) commands for operators/maintainers (contract in `specs/003-docker-multiarch-build/contracts/build-commands.md`).
- **FR-008**: The image MUST declare its platform correctly so that a Docker client can select the appropriate variant on pull/run (manifest platform fields set to `linux/amd64` and `linux/arm64` respectively).
- **FR-009**: Verification of both architectures MUST be possible without requiring two physical machines simultaneously — i.e., via either native builds on each architecture, emulated builds (e.g., buildx + QEMU), or manifest inspection in CI.
- **FR-010**: Changes to satisfy multi-arch support MUST NOT break any existing requirements from `002-docker-swarm-deployment` (scheduling, secrets, failure emails, one-shot runs, no secrets in image).
- **FR-011**: The repository MUST provide a separate executable build script at `docker/build.sh` (distinct from `docker/deploy.sh`) that implements both native and cross-build flows; `docker/deploy.sh` MUST NOT contain `docker build`/`buildx` — it deploys an already-built image (via `SYNC_IMAGE`) produced by `docker/build.sh`.

### Key Entities *(include if feature involves data)*

- **Container Image Variant**: A build artifact of `docker/Dockerfile` for a specific platform (`linux/amd64` or `linux/arm64`); both variants expose the same entrypoint and environment-variable interface.
- **Multi-Arch Manifest**: A single registry reference (manifest list / OCI index) that points to both platform-specific variants, allowing `docker pull` to auto-select the correct one.
- **Build Script (`docker/build.sh`)**: Executable script at `docker/build.sh` (separate from `docker/deploy.sh`) that is the single source of truth for producing `Container Image Variant`(s) / `Multi-Arch Manifest`; it encapsulates native and cross-build flows (see `specs/003-docker-multiarch-build/contracts/build-commands.md`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `docker/build.sh` (wraps `docker build -f docker/Dockerfile -t carddav2fritzbox:local .`) completes successfully on a clean amd64 host and on a clean arm64 host with no Dockerfile changes between the two.
- **SC-002**: A single invocation of `docker/build.sh --push -t <registry>/carddav2fritzbox:<tag>` (wraps `docker buildx build --platform linux/amd64,linux/arm64 --push`) produces both `linux/amd64` and `linux/arm64` images/manifests, verifiable by `docker buildx imagetools inspect` / `docker manifest inspect` showing both platforms.
- **SC-003**: A container built for amd64 and a container built for arm64, given identical configuration and mocked (or real) CardDAV/FritzBox inputs, produce equivalent functional outcomes (same contacts synced, same exit code).
- **SC-004**: 100% of the supported architectures are listed in user-facing `docker/` documentation, and a new operator can successfully build and run the image on either architecture by following only that documentation.
- **SC-005**: No regression in `002-docker-swarm-deployment` acceptance scenarios when exercised on either architecture.

## Assumptions

- The base image `python:3.13-alpine` (current `docker/Dockerfile:3`) already publishes both `linux/amd64` and `linux/arm64` variants, so no base-image change is required unless a future pin breaks this.
- Cross-building will rely on standard Docker tooling (e.g., `docker buildx` with QEMU emulation) rather than custom cross-compilation; the spec does not mandate a specific builder implementation, only the outcome.
- Pure-Python application code plus Pillow wheel/musl builds will cover both architectures without architecture-specific compilation flags; if Pillow requires compilation, Alpine's `apk` build dependencies must be architecture-neutral.
- Registry publishing (Docker Hub / GHCR) is optional; when used, a multi-arch manifest is the expected delivery form, but local per-arch builds remain the primary verified path.
- Operators may build locally from the repository (as stated in 002 Assumptions); pre-built multi-arch images are a convenience, not a requirement for this spec.

## Dependencies

- Depends on `002-docker-swarm-deployment` deliverables in `docker/` (Dockerfile, entrypoint, notify, compose/stack, docs) — this spec constrains that Dockerfile/image to be portable, not replacing it.
- Out of scope: additional architectures beyond amd64 and arm64 (e.g., arm/v7, ppc64le), performance optimization per architecture, and signing/attestation of images.
