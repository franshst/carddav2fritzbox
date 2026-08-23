# Implementation Plan: Docker Swarm Deployment

**Branch**: `002-docker-swarm-deployment` | **Date**: 2026-08-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-docker-swarm-deployment/spec.md`

## Summary

Package the existing carddav2fritzbox CLI as a container image (Alpine base,
per user decision 2026-08-22) and deliver a Docker Swarm stack that runs the
sync on a nightly schedule via `crazymax/swarm-cronjob`. A Python wrapper
(user decision: wrapper may be Python; stdlib-only) invokes the sync, captures
its full output and exit code, and emails both to a configurable recipient via
stdlib `smtplib` only when the sync fails. All credentials arrive as Docker
secrets translated into the utility's documented environment-variable
overrides; non-secret config is bind-mounted. Deliverables live in `docker/`
with separate plain-Docker and Swarm documentation plus an example script that
creates secrets and deploys the stack.

## Technical Context

**Language/Version**: Python 3.13 (image base `python:3.13-alpine`; matches project py310+ target)

**Primary Dependencies**: Runtime unchanged (`requests`, `vobject`, `Pillow`). Wrapper uses Python stdlib only (`smtplib`, `email`, `subprocess`, `logging`) — zero new dependencies. Scheduling: `crazymax/swarm-cronjob` sidecar service in the stack.

**Storage**: None new. Non-secret `config.ini` bind-mounted read-only; secrets mounted at `/run/secrets/` by the Swarm runtime.

**Testing**: pytest for the wrapper (unit: failure detection, email composition; integration: mocked SMTP + failing sync command). Existing sync test suite untouched.

**Target Platform**: Linux Docker Swarm cluster; one-shot task per scheduled trigger.

**Project Type**: Containerized deployment of an existing CLI (build/deploy tooling around `src/main.py`)

**Performance Goals**: Scheduled run completes within the same window as a manual run (<5 min for typical contact lists); notification email within 5 min of a failed run (SC-003).

**Constraints**: Non-interactive; no secrets in files/logs/image (FR-013); fail-fast on missing secrets (FR-014); overlapping triggers skipped, not queued (spec Assumptions).

**Scale/Scope**: Single-stack single-service deployment; ~6 files added under `docker/`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Clean Code (PEP 8)**: PASSED — Python wrapper follows PEP 8; flake8/black/isort cover it.
- **Simple CLI Interface**: PASSED — no new CLI surface; wrapper is the container entrypoint calling the existing `main.py`.
- **Minimal Dependencies**: PASSED — Alpine base + stdlib `smtplib`/`email` avoid any mail-agent package (no msmtp/mailx); runtime dependency set unchanged.
- **Public APIs Only**: PASSED — standard SMTP protocol and public Docker/Swarm primitives (secrets, labels, compose spec).
- **Secure Credential Management**: PASSED — all credentials via Docker secrets → env-var overrides; nothing baked into image or compose file.
- **Modern Python Standards**: PASSED — Python 3.13, type hints, dataclasses where useful.

Post-design re-check (Phase 1): still PASS — contracts add no dependencies or hidden interfaces.

## Project Structure

### Documentation (this feature)

```text
specs/002-docker-swarm-deployment/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── checklists/
│   └── requirements.md  # Spec quality checklist (from /speckit.specify)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   ├── env-secrets.md   # Secret names → environment variable mapping contract
│   └── wrapper.md       # Wrapper behaviour contract (exit codes, capture, email)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
docker/
├── Dockerfile                 # python:3.13-alpine based, installs requirements.txt
├── entrypoint.py              # Python wrapper: secret→env mapping, runs sync, captures output
├── notify.py                  # Failure-email sender (stdlib smtplib), imported by entrypoint.py
├── docker-compose.yml         # Swarm stack: carddav2fritzbox + swarm-cronjob services
├── deploy.sh                  # Example: create all docker secrets, then deploy the stack
├── docker.md                  # Plain-Docker usage documentation
└── swarm.md                   # Swarm stack deployment & scheduling documentation

requirements.txt               # unchanged (runtime deps already present)
tests/
└── unit/
    └── test_wrapper.py        # wrapper unit tests (failure detection, email content)
```

**Structure Decision**: New self-contained `docker/` directory at repository root; no changes to `src/`. The wrapper lives inside `docker/` because it exists solely for the container delivery and is copied into the image.

## Complexity Tracking

> No constitution violations — nothing to justify. The only structural addition is the `docker/` directory; scheduling uses the user-mandated swarm-cronjob mechanism rather than a hand-rolled loop, keeping the service itself a plain one-shot command.
