# Contract: Sync Wrapper Behaviour

**Feature**: 002-docker-swarm-deployment | **Status**: Draft

The wrapper (`docker/entrypoint.py`, helper `docker/notify.py`) is the
container entrypoint. This contract defines its observable behaviour.

## Invocation

- Entrypoint of the container image; no arguments required.
- Runs the sync as a subprocess: `python src/main.py --config $SYNC_CONFIG`
  (log level via existing CLI conventions).

## Processing steps

1. Load secrets → environment per contracts/env-secrets.md (fail fast on
   missing referenced secret files).
2. Execute the sync subprocess, merging stdout+stderr into one stream.
3. Tee the merged stream to container stdout/stderr (platform log remains
   authoritative) while retaining it in memory.
4. Classify outcome: exit code 0 = success; anything else = failure.
5. On failure **and** when `SMTP_HOST`, `EMAIL_FROM`, `EMAIL_TO` are all set:
   send one email (see Email below). Delivery errors are logged as errors;
   they do not alter the process exit code.
6. Exit with the sync's original exit code verbatim.

## Email (failure notification)

| Aspect | Contract |
|--------|----------|
| Trigger | exactly once per failed run, only when mail settings complete |
| Recipient / sender | `EMAIL_TO` / `EMAIL_FROM` |
| Subject | contains `carddav2fritzbox sync failed` and the exit code |
| Body | full captured output (stdout+stderr) plus a final line reporting the exit code |
| Transport | standard SMTP; STARTTLS by default (`SMTP_STARTTLS=true`); optional auth (`SMTP_USERNAME` + secret `smtp_password`) |
| Success runs | no email ever sent |

## Guarantees

- **FR-015**: if email delivery fails, the run's observable outcome (exit
  code, full output in platform logs) is unchanged.
- **FR-014**: missing secret ⇒ exit code `2` before any network contact with
  the FritzBox/CardDAV sources; message names the missing item.
- **Non-interactive**: the wrapper never prompts; absence of configuration is
  an immediate configuration error.

## Testability

Behaviour above maps directly to unit tests: classification, exit-code
propagation, subject/body composition (contains output + exit code), no-email-
on-success, secret-file parsing, fail-fast on missing secret.
