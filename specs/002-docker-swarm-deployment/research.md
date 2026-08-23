# Research: Docker Swarm Deployment

**Feature**: 002-docker-swarm-deployment | **Date**: 2026-08-22

## 1. Container base image

**Decision**: `python:3.13-alpine` as base image; install `requirements.txt` runtime dependencies only.

**Rationale**:

- Alpine satisfies the "minimal operating system image" wish; the official
  `python:*-alpine` images are maintained upstream and pin a modern Python
  (user decision 2026-08-22: Alpine is acceptable).
- Runtime dependencies are wheel-friendly on musl: `requests` and `vobject`
  are pure Python; current `Pillow` releases ship `musllinux` wheels for
  x86_64/aarch64, so no compiler is needed in the common case.
- The dev-only entries in `requirements.txt` (`pytest`, `flake8`, `black`,
  `isort`) must not be installed into the production image; the Dockerfile
  installs only the three runtime packages (explicitly listed or via a
  filtered requirements file — decided at implementation).

**Alternatives considered**:

- `python:3.13-slim` (Debian): larger, glibc; no advantage here.
- Plain `alpine` + `apk add python3`: distro Python version lags; manual
  version management contradicts reproducibility.
- Multi-stage build with compile fallback: kept as contingency if a pinned
  Pillow version lacks a musllinux wheel (then add
  `gcc/musl-dev/python3-dev/zlib-dev/jpeg-dev` in a build stage). Documented
  in docker.md docs rather than defaulting to it.

## 2. Failure-email mechanism

**Decision**: Wrapper written in Python using stdlib `smtplib` + `email`
(user decision 2026-08-22: "wrapper script can be written in Python too").

**Rationale**:

- Constitution principle III (Minimal Dependencies): stdlib SMTP avoids
  installing an MTA (msmtp/mailx) and its configuration dialect entirely;
  zero new packages, zero new image layers.
- The wrapper already needs to run the sync as a subprocess and interpret its
  exit code — Python's `subprocess` does this naturally, and the same process
  can render the email body from the captured output.
- Supports configurable host/port/credentials/starttls, satisfying FR-005.

**Alternatives considered**:

- `msmtp`/`mailx` in the image: adds a dependency and a second config format;
  rejected per Minimal Dependencies.
- Shell wrapper + external mailer: brittle output capture and quoting; less
  testable than pytest-covered Python.

## 3. Secret-to-environment translation

**Decision**: Entrypoint reads secret files under `/run/secrets/<name>` and
exports them as the utility's documented environment-variable overrides before
executing the sync.

**Rationale**:

- Swarm mounts secrets as tempfs files; the sync itself already honours env
  overrides (`FRITZBOX_PASSWORD`, `CARDDAV_<n>_PASSWORD`, …) per README
  "Environment Variables" — reusing that contract means zero changes to
  `src/` (see contracts/env-secrets.md).
- A single declarative mapping table inside the entrypoint keeps the contract
  explicit and testable.

**Alternatives considered**:

- Generating a credentials INI at startup from secrets: writes secrets to disk
  inside the container and duplicates loader logic; rejected.
- Passing secrets directly as compose environment values: leaks values into
  the stack definition; violates FR-013.

## 4. Scheduling and overlap prevention

**Decision**: `crazymax/swarm-cronjob` sidecar service; sync service carries
label `swarm.cronjob.enable=true` and `swarm.cronjob.schedule=<cron>` with a
nightly default; schedule overridable via stack environment without image
rebuild (SC-005).

**Rationale**:

- Mandated by the user's original wishes (docker.md).
- swarm-cronjob triggers a one-shot update of the labelled service only when
  the service has no running task, which yields the spec-assumed
  "skip overlapping runs, don't queue" behaviour without custom locking.
- Cron expression lives in the stack file → redeploy applies it (SC-005).

**Alternatives considered**:

- Host crontab calling `docker`: defeats the purpose of stack deployment.
- Long-running daemon sleeping between runs: restart of the daemon loses
  schedule state; not one-shot semantics.

## 5. Output capture strategy

**Decision**: Wrapper launches the sync via `subprocess.run`, tees merged
stdout+stderr both to the container log (so platform logs stay authoritative)
and into an in-memory buffer used solely for the failure email (contracts/wrapper.md).

**Rationale**:

- Keeps FR-015 honest: even if SMTP delivery fails, the full output is in the
  platform logs and the container exits non-zero.
- Merged stream matches "output of the sync" wording in the wishes; exit code
  is prepended to the email body.

**Alternatives considered**:

- Redirecting sync output to a file mounted out of the container: persists
  potentially credential-bearing logs outside the platform; rejected.

## 6. Exit-code propagation

**Decision**: The container's process exit code equals the sync's exit code;
if the failure email cannot be sent, the wrapper logs the delivery error but
keeps the sync's original exit code (FR-015).

**Rationale**: Platform health monitoring (and swarm-cronjob bookkeeping) see
the true outcome; notification failure is secondary signal, logged loudly.

**Alternatives considered**: Distinct "notification failed" exit code — would
mask the underlying cause in automation; rejected.

## 7. Configuration mounting

**Decision**: Non-secret `config.ini` bind-mounted read-only into the
container; path passed via env/config convention documented in docker.md.

**Rationale**: Separates operator-editable settings (FR-008) from credentials
(FR-007) and keeps the image generic (no config baked in).

**Alternatives considered**: Config as a second Docker secret — supported by
the utility anyway, but bind mount keeps the example simpler and editable;
documented as an option for operators who prefer it.

## 8. Testing approach for the wrapper

**Decision**: pytest unit tests around the wrapper modules: failure detection,
exit-code propagation, email composition (recipient/body contains full output
and exit code), secret-file parsing; integration-style test with a stub SMTP
server (stdlib `smtpd`-like fixture or `aiosmtpd`-free fake transport object)
and a deliberately failing sync command. No live network in tests.

**Rationale**: Matches project testing conventions (pytest); keeps CI hermetic.

## Unresolved items

None remaining — all Technical Context decisions resolved above.
