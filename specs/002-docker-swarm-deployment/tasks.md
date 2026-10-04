---

description: "Task list for Docker Swarm Deployment feature"
---

# Tasks: Docker Swarm Deployment

**Input**: Design documents from `/specs/002-docker-swarm-deployment/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/, quickstart.md — all complete.

**Tests**: Included. plan.md §Testing explicitly defines pytest coverage for the wrapper; test tasks appear first in each story phase and must FAIL before their implementation tasks run.

**Organization**: Tasks grouped by user story (US1–US4 from spec.md) so each story can be implemented and tested independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to
- Exact file paths included in every description

## Path Conventions

- Wrapper code: `docker/` at repository root (per plan.md Structure Decision)
- Tests: `tests/unit/` (existing suite untouched)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the delivery directory and build hygiene

- [x] T001 Create `docker/` directory with `.dockerignore` at repository root excluding `.git/`, `.venv/`, `tests/`, `specs/`, `config.ini`, and any file containing credentials, so the build context stays minimal and secret-free (FR-013)
- [x] T002 [P] Add `docker/` deliverables to version control layout: ensure `docker/*.md` docs and scripts are tracked while no secret values are committed (constitution V)

**Checkpoint**: Directory scaffolding ready.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core wrapper execution engine required by US1 (run the sync) and US2 (classify + notify)

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 Implement sync execution engine in `docker/entrypoint.py`: launch `python src/main.py --config $SYNC_CONFIG` via `subprocess.run`, merge stdout+stderr into one buffer, tee it to container stdout/stderr in real time (platform log stays authoritative per research.md §5), retain buffer in memory, and propagate the child's exit code verbatim as the process exit code (contracts/wrapper.md steps 2–4, 6)
- [x] T004 [P] Write unit tests for execution engine in `tests/unit/test_wrapper.py`: merged capture contains both streams, output is teed to parent streams, exit code 0 and non-zero propagate verbatim, `$SYNC_CONFIG` default `/config/config.ini` honoured (write FIRST, verify FAIL before T003)

**Checkpoint**: Foundation ready - a bare container can execute the sync and report its outcome; user story implementation can begin.

---

## Phase 3: User Story 1 - Scheduled unattended sync as a deployed stack (Priority: P1) 🎯 MVP

**Goal**: Deploying the provided stack runs the sync automatically every night without operator interaction (spec US1).

**Independent Test**: Build image → deploy stack → observe a scheduled one-shot run completing with exit 0 and a correctly updated FritzBox phonebook.

### Implementation for User Story 1

- [x] T005 [US1] Create `docker/Dockerfile`: base `python:3.13-alpine`, install ONLY runtime deps (`requests`, `vobject`, `Pillow`) — not dev tools per research.md §1 — copy `src/` and `docker/entrypoint.py`+`docker/notify.py` into image, set non-root-friendly defaults, `ENTRYPOINT ["python", "/app/docker/entrypoint.py"]`
- [x] T006 [US1] Verify one-shot plain-Docker run per quickstart Scenario 1: `docker build -t carddav2fritzbox:local docker/` succeeds without dev packages; `docker run --rm -v config mount -e FRITZBOX_PASSWORD=... -e CARDDAV_1_PASSWORD=... carddav2fritzbox:local` exits 0, updates phonebook, sends no email
- [x] T007 [US1] Create Swarm stack definition `docker/docker-compose.yml`: service `carddav2fritzbox` (image from T005; read-only bind mount of non-secret `config.ini`; labels `swarm.cronjob.enable=true` and `swarm.cronjob.schedule=${SYNC_CRON:-<nightly-default>}` so schedule changes need redeploy only, never an image rebuild — SC-005; secret references declared but tolerated-absent until US3) plus sidecar service running `crazymax/swarm-cronjob` mounting `/var/run/docker.sock` read-only with configurable `TZ`
- [x] T008 [US1] Validate scheduled execution on a Swarm per quickstart Scenario 2 steps 1, 3, 4: deploy stack, confirm one-shot task runs at trigger time (`docker service logs` shows sync output), re-trigger follows a changed cron expression after redeploy only (US1 acceptance scenarios 1–4)

**Checkpoint**: User Story 1 fully functional and independently testable — hands-off scheduled sync works (MVP!).

---

## Phase 4: User Story 2 - Email notification when a sync fails (Priority: P2)

**Goal**: Failed runs produce exactly one email containing full output + exit code; successful runs send nothing (spec US2).

**Independent Test**: Force a failing sync in a deployed stack → exactly one diagnostic email within ~5 min; successful run → inbox silent.

### Tests for User Story 2 ⚠️ (write FIRST, verify FAIL)

- [x] T009 [P] [US2] Unit tests in `tests/unit/test_notify.py` using a fake SMTP transport object: failure produces exactly one email to `EMAIL_TO` from `EMAIL_FROM`; success produces none; subject contains "carddav2fritzbox sync failed" and the exit code; body contains full captured output plus a final exit-code line; SMTP error raised during send does NOT change the returned outcome (FR-015)

### Implementation for User Story 2

- [x] T010 [P] [US2] Implement `docker/notify.py` stdlib-only sender: settings from env per contracts/env-secrets.md wrapper table (`SMTP_HOST` gates notifications entirely when unset; `SMTP_PORT` default 587; `SMTP_STARTTLS` default true; optional `SMTP_USERNAME`/`SMTP_PASSWORD` auth); compose subject/body per contract wrapper.md email table; raise-on-error so caller decides handling
- [x] T011 [US2] Wire failure branch into `docker/entrypoint.py`: classify exit code ≠ 0 as failure, invoke `notify.send_failure()` exactly once per failed run when mail settings complete, catch and log delivery errors loudly WITHOUT altering the propagated exit code (FR-002, FR-003, FR-004, FR-015)
- [x] T012 [US2] Validate notification behaviour per quickstart Scenario 3: failing config yields exactly one correct email and non-zero task exit; stopped SMTP listener leaves exit code unchanged with delivery error in service logs (SC-003, US2 acceptance scenarios 1–3)

**Checkpoint**: User Stories 1 AND 2 both work independently.

---

## Phase 5: User Story 3 - Credentials supplied exclusively via Docker secrets (Priority: P2)

**Goal**: All passwords arrive as Docker secrets translated to documented env overrides; example script creates secrets + deploys; zero secret leakage anywhere (spec US3).

**Independent Test**: Fresh cluster → run `deploy.sh` → sync authenticates via secrets; inspection of stack/image/scripts/logs finds no secret values.

### Tests for User Story 3 ⚠️ (write FIRST, verify FAIL)

- [x] T013 [P] [US3] Unit tests in `tests/unit/test_wrapper.py` for the secret loader: each mounted `/run/secrets/<name>` maps to its contracted variable with stripped content; missing referenced secret aborts BEFORE any network contact with exit code 2 and a message naming the missing item; empty/unreadable secret file treated as absent (existing precedence rule); contents never echoed (FR-007, FR-014, FR-013)

### Implementation for User Story 3

- [x] T014 [US3] Implement secret→env loader in `docker/entrypoint.py` implementing the mapping table of contracts/env-secrets.md exactly (`fritzbox_password`→`FRITZBOX_PASSWORD`, `carddav_<n>_password`→`CARDDAV_<n>_PASSWORD`, `ftp_password`→`FTP_PASSWORD`, `smtp_password`→`SMTP_PASSWORD`), executed before the subprocess launch from Phase 2
- [x] T015 [US3] Declare all secret references in `docker/docker-compose.yml` under service `carddav2fritzbox` (external secrets, matching names above) and mark `config.ini` mount as carrying NO credentials (FR-008)
- [x] T016 [US3] Create example deployment script `docker/deploy.sh`: creates every required secret via `docker secret create` from operator-supplied prompts/files (never inline values), then deploys the stack; idempotent re-runs update existing secrets; script itself contains no credential values (FR-009, FR-013)
- [x] T017 [US3] Validate per quickstart Scenarios 2 (step 2), 4, and 5: grep artifacts for password finds nothing (SC-004); removed-secret deploy fails fast with exit 2 naming the item; overlapping trigger is skipped by swarm-cronjob (US3 acceptance scenarios 1–3, edge cases)

**Checkpoint**: User Stories 1, 2, AND 3 all work independently; deployment is production-usable.

---

## Phase 6: User Story 4 - Separate documentation for Docker and Swarm usage (Priority: P3)

**Goal**: An operator can follow either `docker/docker.md` or `docker/swarm.md` alone and succeed (spec US4).

**Independent Test**: New user completes each path using only its document.

### Implementation for User Story 4

- [x] T018 [P] [US4] Write plain-Docker usage doc `docker/docker.md`: building the image, running once with bind-mounted config and either `-e` variables or manually created `--secret`s, `$SYNC_CONFIG` convention, exit-code meanings (FR-011)
- [x] T019 [US4] Write Swarm deployment doc `docker/swarm.md`: prerequisites (swarm-cronjob sidecar), secret creation table mirroring contracts/env-secrets.md, `deploy.sh` walkthrough, schedule customisation via cron expression + redeploy (SC-005), overlap-skip semantics, failure-email setup including SMTP settings, troubleshooting mapping to quickstart scenarios
- [x] T020 [US4] Follow-the-docs dry run: execute quickstart Scenarios 1–2 strictly via `docker/docker.md` and Scenarios 3–5 strictly via `docker/swarm.md`, fixing each document where a step is ambiguous or missing (US4 acceptance scenarios 1–2)

**Checkpoint**: All four user stories independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final verification across all stories

- [x] T021 Run full lint/format gate over new Python files: `.venv/bin/flake8 docker/ tests/unit/test_wrapper.py tests/unit/test_notify.py` and `.venv/bin/black --check` / `isort --check` (constitution I)
- [x] T022 Run complete test suite `.venv/bin/pytest -v` ensuring existing sync tests remain green alongside new wrapper tests
- [x] T023 Execute the full `specs/002-docker-swarm-deployment/quickstart.md` top-to-bottom as final end-to-end validation and record results
- [x] T024 Update root `README.md` with a short "Docker / Swarm" section linking to `docker/docker.md` and `docker/swarm.md`
- [x] T025 Create sample environment file `docker/.env.example` containing commented example values for every variable consumed by `docker/deploy.sh` and `docker/docker-compose.yml`: `SYNC_IMAGE` (default `carddav2fritzbox:local`), `SYNC_CRON` (default `0 3 * * *`), `TIMEZONE` (default `Europe/Amsterdam`), `SYNC_CONFIG_PATH` (default `./config.ini`), `SYNC_EXPECTED_SECRETS` (default `fritzbox_password`), `STACK_NAME` (default `carddav2fritzbox`), `SMTP_HOST`, `SMTP_PORT` (default `587`), `SMTP_STARTTLS` (default `true`), `SMTP_USERNAME`, `EMAIL_FROM`, `EMAIL_TO`; include header comment explaining that secrets (`FRITZBOX_PASSWORD`, `CARDDAV_*_PASSWORD`, `SMTP_PASSWORD`, `FTP_PASSWORD`) must NOT be placed in `.env` but created via `docker secret create` / `docker/deploy.sh`, and that real `.env` must be git-ignored
- [x] T026 Update Swarm documentation `docker/swarm.md` to document the sample env file: add note in Prerequisites or §3/§4 that `docker/.env.example` lists all supported variables, show `cp docker/.env.example docker/.env` / edit workflow, explain that `docker stack deploy` and `docker/deploy.sh` read `.env` via compose interpolation, and link to `contracts/env-secrets.md` for secret vs. plain-env distinction

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none — start immediately
- **Foundational (Phase 2)**: depends on T001; BLOCKS all user stories (entrypoint engine is the container's core)
- **US1 (Phase 3)**: needs Foundational (T003) — image entrypoint calls it
- **US2 (Phase 4)**: needs Foundational; integrates with US1's deployed stack for validation but implementation is independent
- **US3 (Phase 5)**: loader hooks into the same entrypoint; validation uses US1's stack; independent of US2
- **US4 (Phase 6)**: documents the finished behaviours of US1–US3, so comes last
- **Polish (Phase 7)**: after all stories — includes sample `.env` (T025 → T026, where T026 depends on T025)

### User Story Dependencies

- **US1**: Foundational only — no cross-story dependency
- **US2**: Foundational only — notify branch is additive to entrypoint
- **US3**: Foundational only — loader precedes subprocess start inside entrypoint
- **US4**: content-wise depends on US1–US3 decisions being final

### Within Each Story

Tests (where present) written first and verified failing → implementation → story-specific validation task last.

### Parallel Opportunities

- T002, T004 (and later T009, T013, T018) are single-file tasks runnable in parallel within/beside their phases
- US2 and US3 implementations touch different files except two small entrypoint insertion points — coordinate T011/T014 or sequence them
- With multiple developers: US2 and US3 can proceed simultaneously after Phase 3 checkpoint
- T025 and T026 are sequential (T026 documents T025); both are independent of T021–T024 polish checks and can run in parallel with lint/test tasks

```bash
# Example parallel batch after Foundational:
Task: "Create docker/Dockerfile (T005)"
# then after T007 exists:
Task: "Implement docker/notify.py (T010)"   # US2, separate file
Task: "Secret loader unit tests (T013)"     # US3, test file
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 + Phase 2 (foundation)
2. Complete Phase 3 → **STOP and VALIDATE** via T006/T008: nightly unattended sync already delivers the core value
3. Deploy/demo if ready

### Incremental Delivery

1. Foundation → US1 (MVP) → US2 (failure visibility) → US3 (secure production credentials) → US4 (operator docs)
2. Each checkpoint leaves the system deployable and demonstrably better

### Parallel Team Strategy

After the Phase 3 checkpoint: Developer A takes US2 (notify path), Developer B takes US3 (secrets path); merge order irrelevant; US4 written once both land.

---

## Notes

- Every task cites exact file paths; wrapper code lives exclusively in `docker/`
- No changes to `src/` are planned or permitted by this feature's design
- Commit after each task or logical group; stop at every Checkpoint to validate the story independently
