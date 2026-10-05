# Research: Docker Multi-Architecture Build

**Feature**: 003-docker-multiarch-build | **Date**: 2026-08-30 | **Branch**: `003-docker-multiarch-build`

**Context**: Starting point is a working Docker Swarm with heterogeneous nodes (amd64 + arm64). The spec requires `docker/Dockerfile` to build and run identically on both architectures, with a documented single-host cross-build that produces a multi-arch manifest so Swarm correctly pulls the matching variant per node. Per user update 2026-08-30, build logic must live in a separate `docker/build.sh` distinct from `docker/deploy.sh`.

## 1. Base image dual-architecture support

**Decision**: Keep `python:3.13-alpine` as `FROM` (current `docker/Dockerfile:3`) without any `--platform` pin.

**Rationale**:
- Docker Hub inspection (`docker buildx imagetools inspect python:3.13-alpine` or Hub tags page) shows upstream publishes `linux/amd64` and `linux/arm64` manifests for every `3.13-alpine` variant. No alternative base needed.
- Alpine is already the user-mandated minimal image (002 research §1). Keeping it avoids size/reproducibility churn.
- Pinning `--platform=linux/amd64` would violate FR-004; omitting the flag lets Docker resolve the variant matching the build host automatically (and `buildx --platform` controls the target).

**Alternatives considered**:
- `python:3.13-slim` (Debian glibc) — also dual-arch but larger and abandoned per 002 decision.
- Explicit multi-stage with arch-specific apk — unnecessary; no binary base component diverges by arch.

## 2. Python runtime dependencies on both architectures

**Decision**: No Dockerfile change; `pip install --no-cache-dir requests vobject Pillow` continues to work on both platforms via musllinux wheels.

**Rationale**:
- `requests` and `vobject` are pure Python — no native code, trivially portable.
- `Pillow` publishes `musllinux_1_1` + `musllinux_1_2` wheels for both `x86_64` and `aarch64` since 9.x; `pip` on Alpine's Python 3.13 resolves the correct wheel, so no compiler is invoked.
- If a future Pillow pin lacks an `aarch64` musllinux wheel, fallback (not default) is a build stage with `apk add gcc musl-dev python3-dev jpeg-dev zlib-dev` — kept as documented contingency, not baked into the default Dockerfile to preserve minimal layers.

**Scope note (Q5 B)**: The fallback above is **out-of-scope** for this feature's default build — `docker/Dockerfile:8` and `docker/build.sh` remain compiler-free (no `apk` build stage). It is documented only for future pin changes; no task implements it unless a wheel actually goes missing.

**Alternatives considered**:
- Pre-building separate requirements per arch — adds maintenance with no benefit.
- Vendoring wheels — contra Minimal Dependencies.

## 3. Single-host cross-build tooling (native vs emulated) — separate build script

**Decision**: Encapsulate both paths in a **separate `docker/build.sh`**, distinct from `docker/deploy.sh` per user update 2026-08-30:
- **Native build** (default): `docker/build.sh` wraps `docker build -f docker/Dockerfile -t carddav2fritzbox:local .`
- **Cross-build (one host)**: `docker/build.sh --push -t <registry>/carddav2fritzbox:<tag>` wraps `docker buildx build --platform linux/amd64,linux/arm64 -t <registry>/carddav2fritzbox:<tag> --push -f docker/Dockerfile .`

`deploy.sh` is trimmed to **deploy-only** (secrets + `docker stack deploy`); it must not contain any build logic. `build.sh` is the single source of truth for all `docker build`/`buildx` invocations, and `docker/docker.md` + `docker/swarm.md` reference it.

**Rationale**:
- `buildx` is the Docker-official multi-platform builder (stable since Docker 19.03, bundled in modern engines). Using QEMU user-mode emulation via `tonistiigi/binfmt` is the standard CI pattern and requires zero Dockerfile changes.
- `--push` is required for a two-platform `buildx build` when no local container driver supports loading a multi-arch OCI layout into the local daemon (default `docker` driver). Buildx `--load` only supports single platform; the manifest-list use case necessarily pushes.
- Maintainer's single amd64 host (typical CI runner) can thus produce the arm64 variant without a second machine, satisfying P2.

**Alternatives considered**:
- Two separate tagged images (`:amd64`, `:arm64`) + manual `docker manifest create` — functionally equivalent but extra steps; still usable as fallback if the registry disallows buildx push.
- Native two-host build — works but contradicts the "single invocation" requirement; kept as valid but not the primary documented path.

## 4. Swarm heterogeneous scheduling and image distribution

**Decision**: No change to `docker/docker-compose.yml` service definition; require that `SYNC_IMAGE` (compose variable `services.carddav2fritzbox.image`) point at a **multi-arch manifest reference** when the Swarm mixes architectures.

**Rationale**:
- Docker Swarm's scheduler pulls the image on whichever node it places the one-shot task. When the reference is a manifest list / OCI index, the Docker engine on that node automatically selects the manifest whose `platform.architecture` matches the node (amd64 vs arm64). No placement constraints by architecture needed.
- This matches the project's swarm.md §6 troubleshooting already warning "push the image to a registry all nodes can pull; set `SYNC_IMAGE`" — now clarified to require a multi-arch reference for mixed clusters.
- Local-only images (`carddav2fritzbox:local`) only exist on the build node — unsuitable for mixed Swarm; documented as single-host/standalone case.

**Alternatives considered**:
- Per-arch placement constraints (`node.labels.arch == amd64` with two services) — doubles stack complexity, unnecessary when manifest list solves it at the registry layer.
- Building on every Swarm node at deploy time — operationally fragile, not declarative.

## 5. Verification without two physical hosts

**Decision**: Verification contract: after a cross-build, run `docker buildx imagetools inspect <ref>` or `docker manifest inspect <ref>` and assert both `linux/amd64` and `linux/arm64` entries exist; plus a local smoke run on the native arch.

**Rationale**:
- Hosts of a single arch can still assert the arm64 artifact was produced by inspecting the manifest. Combined with the pure-Python / wheel reasoning (§2), manifest presence is a sufficient correctness signal for build; runtime parity is then covered by the same sync exit-code semantics on whichever arch is available locally.
- Avoids mandating that CI has both ARM and x86 runners (though adding a second arch runner remains ideal as follow-up).

**Alternatives considered**:
- Mandating two native runners in CI — strongest signal but raises entry barrier; documented as optional enhancement, not a gate for this spec.

## 6. Documentation placement

**Decision**: Update `docker/docker.md` §1 (Build the image) to list supported platforms and reference `docker/build.sh` (native default vs `--push` cross-build); update `docker/swarm.md` §1 (Build or obtain the image) + §3/6 to clarify registry + manifest requirement and verification command via `build.sh`.

**Rationale**: In 002 `docker/docker.md` and `docker/swarm.md` are already the operator's first contact points. Adding multi-arch info there satisfies FR-007 / AC for P3 without new files.

**Alternatives considered**: New `docker/multiarch.md` — adds a file for content that fits in two existing sections; rejected for discoverability.

## 7. Build vs deploy script separation

**Decision**: New `docker/build.sh` handles all image construction; `docker/deploy.sh` handles only secret creation and `docker stack deploy`.

**Rationale**:
- Separation of concerns: building (needs `buildx`/QEMU, registry credentials for push) vs deploying (needs Swarm secrets, stack config, cron labels) have different prerequisites and are run at different times and by different actors (maintainer/CI vs operator).
- Per user instruction 2026-08-30: explicitly requires a separate build script.
- Prevents drift: raw `docker build` commands appear once (in `build.sh`); docs and CI call the script.

**Alternatives considered**:
- Adding build flags to `deploy.sh` (`--build` mode) — couples build and deploy, contradicts explicit user requirement for separation, and makes CI's build-only path awkward.
- No script, docs-only commands — does not satisfy the new requirement and duplicates command strings across docs/CI.

**Build script interface (contract in `contracts/build-commands.md`)**:
- `docker/build.sh` — native build, `carddav2fritzbox:local`, current host arch
- `docker/build.sh -t <registry>/carddav2fritzbox:<tag>` — native build with custom tag
- `docker/build.sh --push -t <registry>/carddav2fritzbox:<tag>` — cross-build `linux/amd64,linux/arm64` and push manifest list
- `docker/build.sh --help` — prints usage
- `deploy.sh` must not invoke `docker build`/`buildx`; verification by grepping.

## Unresolved items

None — all Technical Context decisions resolved above. No `NEEDS CLARIFICATION` remains.

## Sources

- Docker official images library: `python:3.13-alpine` multi-arch manifests on Docker Hub (linux/amd64, linux/arm64)
- PyPI / `pip` index: `Pillow` musllinux wheels for `x86_64` and `aarch64`
- Docker docs: `buildx build --platform`, `buildx imagetools inspect`, manifest list / OCI index, Swarm image pull behavior
- Existing repo artifacts: `002-docker-swarm-deployment/research.md`, `docker/Dockerfile`, `docker/docker-compose.yml`, `docker/docker.md`, `docker/swarm.md`
