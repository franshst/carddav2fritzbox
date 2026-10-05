# Tasks: Docker Multi-Architecture Build

**Input**: Design documents from `/specs/003-docker-multiarch-build/` (spec.md, plan.md, research.md, data-model.md, contracts/build-commands.md, contracts/image-manifest.md, quickstart.md)
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md
**Constitution**: `.specify/memory/constitution.md` (Clean Code, Minimal Dependencies, Secure Credentials checked)

**Context**: Starting point is a working Docker Swarm with heterogeneous nodes (amd64 + arm64). `docker/Dockerfile` must build on both. Build logic must live in a **separate `docker/build.sh`** distinct from `docker/deploy.sh` (user update 2026-08-30). Swarm pulls the correct variant per node via a registry manifest list produced by `build.sh --push`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Common prerequisites, no story-specific logic

- [x] T001 Verify tooling prerequisites for multi-arch builds in repo — check `docker --version`, `docker buildx version` and QEMU binfmt availability in `docker/` docs context
- [x] T002 [P] Inspect current `docker/Dockerfile` at `docker/Dockerfile:1` for arch-specific pins and document findings in `specs/003-docker-multiarch-build/research.md` §1 check
- [x] T003 [P] Ensure `docker/build.sh` placeholder exists and is executable at `docker/build.sh` (`chmod +x`) — create skeleton if missing

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Verify base portability before any story work — MUST complete before US1/US2/US3

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T004 Verify `python:3.13-alpine` base publishes `linux/amd64` and `linux/arm64` manifests (via `docker buildx imagetools inspect python:3.13-alpine` or Hub) and document in `docker/build.sh` header comment
- [x] T005 Verify Python dependencies install on both arches — confirm `requests`, `vobject`, `Pillow` wheels exist for `musllinux` `x86_64` and `aarch64` and that `docker/Dockerfile:8` pip line needs no arch-conditional logic
- [x] T006 Verify separation of concerns baseline — grep `docker/deploy.sh` for `docker build`/`buildx` and ensure it is deploy-only; record result as precondition for `data-model.md` Entity 4 validation in `docker/deploy.sh`
- [x] T007 [P] Create or update `docker/.dockerignore` if needed to keep build context minimal (should already exist at `.dockerignore` at repo root — verify it excludes `.venv`, `tests`, etc.)

**Checkpoint**: Foundation ready — base image and deps are dual-arch, build/deploy separation baseline confirmed

---

## Phase 3: User Story 1 — Build and run the image natively on amd64 and arm64 (Priority: P1) 🎯 MVP

**Goal**: Operator on either amd64 or arm64 can build `docker/Dockerfile` and run the sync container with identical semantics. Build via `docker/build.sh` (native default).

**Independent Test**: `docker/build.sh` on amd64 host and on arm64 host (or emulated) completes without arch errors; `docker run --rm carddav2fritzbox:local` executes sync/exits with same codes as spec.md US1 AC1–AC3. Also `docker/build.sh --help` and `! grep -q "docker build" docker/deploy.sh`.

### Implementation for User Story 1

- [x] T008 [US1] Implement native build path in `docker/build.sh` — parse `-t/--tag`, `-f/--file`, `-h/--help`, default `carddav2fritzbox:local`, default `docker/Dockerfile`, implement `docker build -f <file> -t <tag> .` with error handling and `--help` printing
- [x] T009 [P] [US1] Add platform override and tag validation to `docker/build.sh` — support `--platform <list>` for native override, reject missing/invalid args, ensure `FR-004` (no pinned `--platform` in `docker/Dockerfile`)
- [x] T010 [US1] Verify `docker/Dockerfile` is platform-agnostic in `docker/Dockerfile` — remove any `--platform=linux/amd64` pin if present, keep `FROM python:3.13-alpine` at `docker/Dockerfile:3`, ensure `pip install` at `docker/Dockerfile:8` is arch-neutral
- [x] T011 [P] [US1] Add native build smoke verification snippet to `docker/build.sh` header/comments referencing `contracts/build-commands.md` native section — ensure `docker run --rm carddav2fritzbox:local --help` is documented
- [x] T012 [US1] Validate US1 end-to-end via `quickstart.md` §1 in `specs/003-docker-multiarch-build/quickstart.md` — run `docker/build.sh`, `docker run --rm carddav2fritzbox:local --help`, `docker/build.sh --help`, and `! grep -q "docker build" docker/deploy.sh` locally

**Checkpoint**: At this point, `docker/build.sh` native builds work on either arch; `deploy.sh` is proven deploy-only

---

## Phase 4: User Story 2 — Emulated / cross-build produces both images from a single host (Priority: P2)

**Goal**: Maintainer/CI on a single host (typically amd64) can produce both `linux/amd64` and `linux/arm64` variants in one invocation via `docker/build.sh --push` and push a manifest list.

**Independent Test**: `docker/build.sh --push -t <registry>/carddav2fritzbox:<tag>` completes and `docker buildx imagetools inspect <registry>/carddav2fritzbox:<tag>` shows both `linux/amd64` and `linux/arm64` per `contracts/build-commands.md` and `contracts/image-manifest.md` (SC-002). No second physical host required.

### Implementation for User Story 2

- [x] T013 [US2] Implement cross-build `--push` path in `docker/build.sh` — when `--push` is set, require `-t <registry>:<tag>`, default `--platform linux/amd64,linux/arm64`, ensure builder exists (`docker buildx create --use` if needed), run `docker buildx build --platform <platforms> -t <tag> -f <file> --push .` with QEMU hint on failure
- [x] T014 [US2] Add `--push` validation and error messaging in `docker/build.sh` — fail if `--push` given with `carddav2fritzbox:local` (no registry), print hint for QEMU binfmt (`tonistiigi/binfmt --install all` / `docker/setup-qemu-action`), handle `--load` misuse (single-platform only)
- [x] T015 [P] [US2] Document fallback path in `docker/build.sh` comments per `contracts/build-commands.md` fallback — separate pushes + `docker manifest create --amend` + `docker manifest push` as fallback when `buildx --push` is not viable
- [x] T016 [US2] Implement or verify manifest verification helper in `docker/build.sh` or as comment — example `docker buildx imagetools inspect <tag> | grep -q linux/amd64 && grep -q linux/arm64` per `contracts/image-manifest.md` contract test
- [x] T017 [P] [US2] Update `docker/docker-compose.yml` comment at `docker/docker-compose.yml:37` (`SYNC_IMAGE`) to note heterogeneous Swarm must use `build.sh --push` registry reference (manifest list) — add one-line comment referencing `contracts/image-manifest.md`
- [x] T018 [US2] Validate US2 end-to-end via `quickstart.md` §2–§3 — create `buildx` builder if needed, `docker/build.sh --push -t <registry>:test-multiarch` to a test registry (or `--dry-run` if no registry), then `docker buildx imagetools inspect` asserts both platforms; plus smoke parity check per `quickstart.md` §3 using existing `002` test fixtures (mocked CardDAV/FritzBox) asserting identical exit codes and phonebook on native vs cross-built image (SC-003)

**Checkpoint**: At this point, single-host cross-build works; mono-arch and manifest-list images are both producible; Swarm manifest contract is satisfied

---

## Phase 5: User Story 3 — Documentation tells the operator which platform they get (Priority: P3)

**Goal**: Operator reading `docker/` docs sees supported platforms and knows how to invoke `docker/build.sh` for native vs cross-build.

**Independent Test**: New user follows only `docker/docker.md` and `docker/swarm.md` and can build/run on their arch via `docker/build.sh`; `grep -i "build.sh\|amd64\|arm64\|buildx\|imagetools"` passes per `quickstart.md` §5 (SC-004).

### Implementation for User Story 3

- [x] T019 [P] [US3] Update `docker/docker.md` §1 (Build the image) in `docker/docker.md` — state supported platforms `linux/amd64` + `linux/arm64`, reference `docker/build.sh` native (`./docker/build.sh`) and cross (`./docker/build.sh --push -t <registry>:<tag>`), verification via `imagetools inspect`, keep `docker/build.sh` as single source of truth (per `data-model.md` Entity 3)
- [x] T020 [P] [US3] Update `docker/swarm.md` §1 (Build or obtain the image) and §3/§6 in `docker/swarm.md` — add heterogeneous Swarm note (starting point: working Swarm with mixed nodes), require `SYNC_IMAGE` be the `build.sh --push` manifest reference, show `SYNC_IMAGE=<registry>:<tag> ./docker/deploy.sh`, add troubleshooting for `no matching manifest` → re-run `build.sh --push`, note `buildx imagetools inspect` check
- [x] T021 [US3] Validate documentation coverage per `data-model.md` Entity 5 — grep `docker/docker.md` and `docker/swarm.md` for `build.sh` + `linux/amd64` + `linux/arm64` and confirm `quickstart.md` §5 passes

**Checkpoint**: All user stories should now be independently functional; docs reference the build script, not duplicated raw commands

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, cleanup, and cross-story guarantees

- [x] T022 Ensure `docker/build.sh` passes shellcheck and prints ` --help` correctly — run `shellcheck docker/build.sh` and `docker/build.sh --help` at `docker/build.sh:1`
- [x] T023 [P] Run `quickstart.md` full validation in `specs/003-docker-multiarch-build/quickstart.md` — execute §1 native, §2 cross-build (if registry available or dry-run), §4 Swarm deploy check (mixed nodes via `SYNC_IMAGE`), §5 docs grep; capture results
- [x] T024 [P] Verify no regression of `002-docker-swarm-deployment` acceptance scenarios — run existing `tests/` suite (`pytest tests/`) and confirm swarm `deploy.sh` still creates secrets + `docker stack deploy` only (no build) at `docker/deploy.sh`
- [x] T025 [P] Verify constitution gates after build script addition — check `docker/build.sh` adds no runtime image dependencies (still `requests`, `vobject`, `Pillow` only at `docker/Dockerfile:8`), no secrets in image/logs, `chmod +x docker/build.sh`
- [x] T026 Polish task — remove any temporary test images/tags and note cleanup in `specs/003-docker-multiarch-build/quickstart.md` cleanup section

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational
  - Can proceed in parallel if staffed, or sequentially P1 → P2 → P3
- **Polish (Phase 6)**: Depends on all desired user stories being complete (at minimum P1; P1+P2 recommended for MVP of multi-arch)

### User Story Dependencies

- **US1 (P1)**: Can start after Foundational — no dependency on US2/US3; delivers MVP (native dual-arch via single script)
- **US2 (P2)**: Depends on US1's `docker/build.sh` native baseline (extends same script with `--push`); independently testable via manifest inspect
- **US3 (P3)**: Depends on US1/US2 script interfaces being stable — docs reference final `build.sh` invocations; independently testable via grep/doc-follow

### Within Each User Story

- Script interface before verification
- Docs updated after script interface is stable
- `quickstart.md` section for that story validates it before moving on

### Parallel Opportunities

- T002 and T003 can run in parallel (different files: Dockerfile vs build.sh skeleton)
- T004 vs T005 vs T007 in Foundational are independent
- T009 and T011 (US1) are parallel (different concerns in same file but distinct sections)
- T015 and T017 (US2) are parallel (build.sh fallback comments vs compose comment)
- T019 and T020 (US3) are parallel (two docs, different files) — enabled by final `[P]` markers
- Polish T023, T024, T025 can run in parallel (validation vs tests vs constitution)

---

## Parallel Example: User Story 3 (Documentation)

```bash
# Two docs, different files — can be updated in parallel:
Task: "Update docker/docker.md §1 (Build the image) in docker/docker.md"
Task: "Update docker/swarm.md §1 and §3/§6 in docker/swarm.md"
```

## Parallel Example: Foundational

```bash
# Verify base image manifests while also checking dependency wheels:
Task: "Verify python:3.13-alpine base publishes linux/amd64 and linux/arm64 manifests"
Task: "Verify Python dependencies install on both arches"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T003)
2. Complete Phase 2: Foundational (T004–T007) — CRITICAL
3. Complete Phase 3: US1 (T008–T012)
4. **STOP and VALIDATE**: `docker/build.sh`, `docker/build.sh --help`, `! grep "docker build" docker/deploy.sh`, native `docker run` smoke — deploy per `quickstart.md` §1
5. Demo: building on either amd64 or arm64 host works

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. + US1 → Native multi-arch via one script (MVP!) → Deploy/Demo
3. + US2 → Cross-build ` --push` + manifest list → Test `imagetools inspect` → Mixed Swarm deploy → Deploy/Demo
4. + US3 → Docs updated to reference build script → New operator can follow docs alone → Deploy/Demo
5. Polish → `quickstart.md` §1–5, `pytest`, `shellcheck`, constitution check

### Parallel Team Strategy

With multiple developers:

1. All together: Setup + Foundational (T001–T007)
2. Once Foundational is done:
   - Developer A: US1 (build.sh native — T008–T012)
   - Developer B: prepared to extend to US2 cross-build — waits for T008 baseline, then T013–T018
   - Developer C: Docs skeleton — waits for US1/US2 interfaces, then T019–T021
3. Polish together (T022–T026)

---

## Notes

- [P] tasks = different files, no dependencies — safe to parallelize
- [Story] label maps task to user story for traceability (US1 = native, US2 = cross-build, US3 = docs)
- Each story is independently completable and testable per spec's Independent Test and quickstart.md
- Build vs deploy separation is enforced: `docker/build.sh` builds, `docker/deploy.sh` deploys — never both in one file
- Stop at any checkpoint (Foundational, US1, US2) to validate that story independently
- File paths are exact: `docker/build.sh`, `docker/Dockerfile`, `docker/deploy.sh`, `docker/docker-compose.yml`, `docker/docker.md`, `docker/swarm.md`


## Phase 7: Convergence

- [x] T027 Add heterogeneous Swarm comment to `docker/docker-compose.yml` at `docker/docker-compose.yml:37` noting `SYNC_IMAGE` must be a `docker/build.sh --push` multi-arch manifest reference for mixed amd64+arm64 nodes per `plan: Project Structure` and `spec.md:FR-006/FR-008` (missing)
- [x] T028 Update `docker/swarm.md:100` troubleshooting table to mention heterogeneous manifest case and `docker/build.sh --push` fix per `spec.md:FR-007` and `spec.md:US3/AC1` (partial)
- [x] T029 Add `docker buildx imagetools inspect` verification note to `docker/docker.md:7` §1 per `spec.md:FR-008` and `contracts/build-commands.md:60` (partial)

## Phase 8: Actual Image Build & Test Execution

**Purpose**: Execute real Docker builds and container tests to prove FR-001–FR-011 / SC-001–SC-005 (previous phases only validated via docs/grep)

- [x] T030 [US1] Execute native build via `docker/build.sh` in repo root — run `docker/build.sh -t carddav2fritzbox:local-test` at `docker/build.sh:1` using `docker/Dockerfile:3`, capture build log to `/tmp/build-native.log`, verify exit 0 and image exists via `docker images`
- [x] T031 [P] [US1] Smoke-test native image at `docker/build.sh` output — run `docker run --rm carddav2fritzbox:local-test --help` and `docker run --rm -v $PWD/config.ini:/config/config.ini:ro -v /tmp/fb_secret:/run/secrets/fritzbox_password:ro -e SYNC_EXPECTED_SECRETS=fritzbox_password carddav2fritzbox:local-test` and verify exit codes per `spec.md:US1/AC3` (0 on success path, 2 on missing-secret path)
- [x] T032 [US2] Start ephemeral local registry for cross-build testing at `docker/docker-compose.yml` — run `docker run -d -p 5000:5000 --name carddav2fritzbox-registry-test registry:2` and verify `curl -f http://localhost:5000/v2/` succeeds (teardown in T035)
- [x] T033 [US2] Execute cross-build and push via `docker/build.sh` — run `docker/build.sh --push -t localhost:5000/carddav2fritzbox:test-multiarch` at `docker/build.sh:114` (requires buildx+QEMU from `research.md:42`), verify `docker buildx imagetools inspect localhost:5000/carddav2fritzbox:test-multiarch` contains both `linux/amd64` and `linux/arm64` per `contracts/image-manifest.md:64`
- [x] T034 [P] [US2] Parity test cross-built images at `docker/build.sh` output — pull both variants `docker pull --platform linux/amd64 localhost:5000/carddav2fritzbox:test-multiarch` and `docker pull --platform linux/arm64 ...`, run each with identical `config.ini` mock per `quickstart.md:3` and `spec.md:SC-003`, compare exit codes and phonebook output for equality
- [x] T035 Polish cleanup of build-test artifacts at `docker/build.sh` and registry — run `docker rm -f carddav2fritzbox-registry-test; docker rmi carddav2fritzbox:local-test localhost:5000/carddav2fritzbox:test-multiarch; docker buildx rm carddav2fritzbox 2>/dev/null || true` and remove `/tmp/build-native.log`

