# Quickstart: Docker Swarm Deployment Validation

**Feature**: 002-docker-swarm-deployment

End-to-end validation scenarios proving the feature works. Implementation
details live in `tasks.md` / `plan.md`; this is the run guide.

## Prerequisites

- A Docker Swarm cluster (`docker swarm init` on a single node suffices)
- The repository checked out (for building the image)
- A non-secret `config.ini` prepared per README (no credentials inside)
- SMTP access from the cluster for failure-notification tests
- `crazymax/swarm-cronjob` reachable as declared in the stack file

## Scenario 1 — Build and run once with plain Docker

1. Build the image:
   ```bash
   docker build -t carddav2fritzbox:local docker/
   ```
   **Expected**: image builds on the Alpine base without installing dev-only
   requirements.

2. Run one sync with secrets provided manually:
   ```bash
   docker run --rm \
     -v "$PWD/config.ini:/config/config.ini:ro" \
     -e FRITZBOX_PASSWORD=... -e CARDDAV_1_PASSWORD=... \
     carddav2fritzbox:local
   ```
   **Expected**: sync completes, exit code 0, **no email sent**, FritzBox
   phonebook matches a manual run's result. See `docker/docker.md`.

## Scenario 2 — Deploy the stack via the example script

1. Run the example script (`docker/deploy.sh`) after filling in secret values.
   **Expected**: all required secrets created (`docker secret ls`), stack
   deployed (`docker stack services <stack>` shows both services).

2. Inspect artifacts for leaks:
   ```bash
   grep -r <password> docker/ && echo LEAK
   ```
   **Expected**: no matches in compose file/scripts/docs (SC-004).

3. Wait for the first scheduled trigger (or temporarily set a short cron
   expression and redeploy).
   **Expected**: one-shot task runs; `docker service logs` shows the sync
   output; phonebook updated (US-1 scenarios 1–3).

4. Change the cron label value, redeploy.
   **Expected**: next trigger follows the new schedule; no image rebuild
   needed (SC-005).

## Scenario 3 — Failure notification

1. Induce a failure (e.g. unreachable FritzBox URL in config) and redeploy.
2. Trigger a run.
   **Expected**:
   - exactly one email at `EMAIL_TO` within ~5 minutes of run end;
   - subject mentions the failure and exit code;
   - body contains the full captured output plus the exit code line;
   - container/service task exits non-zero (SC-003).
3. Stop the local SMTP listener, re-trigger a failing run.
   **Expected**: delivery error appears in service logs, but the task still
   exits with the sync's original non-zero code (FR-015).

## Scenario 4 — Missing secret fail-fast

1. Deploy with one referenced secret removed.
2. Trigger a run.
   **Expected**: immediate exit code 2, log names the missing secret, no
   contact attempted with FritzBox/CardDAV sources (FR-014).

## Scenario 5 — Overlap skip

1. Set a very short schedule while pointing the config at a slow/blocked
   endpoint so a run stays active past the next trigger.
   **Expected**: swarm-cronjob skips the overlapping trigger; no concurrent
   runs (spec Assumptions).

## References

- Behavioural guarantees: [contracts/wrapper.md](contracts/wrapper.md)
- Secret naming/mapping: [contracts/env-secrets.md](contracts/env-secrets.md)
- Operator documentation deliverables: `docker/docker.md`, `docker/swarm.md`
