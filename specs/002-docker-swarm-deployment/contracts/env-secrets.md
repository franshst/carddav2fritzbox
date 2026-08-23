# Contract: Secrets ↔ Environment Mapping

**Feature**: 002-docker-swarm-deployment | **Status**: Draft

This is the normative contract between the Swarm Secret Set, the wrapper
(`docker/entrypoint.py`), and the sync utility's existing environment-variable
override rules (README "Environment Variables").

## Rules

1. Every secret is mounted by the Swarm runtime at `/run/secrets/<name>`.
2. Before invoking the sync, the wrapper reads each mounted secret file and
   exports its **stripped** content as the corresponding environment variable.
3. Environment variables set this way override config-file values; empty or
   unreadable secret files are treated as absent (existing precedence rule).
4. Secret file contents are never written to logs, stdout, or error messages.
5. A secret referenced by the stack but missing at `/run/secrets/` at startup
   aborts the run with exit code `2` (configuration error) and a message naming
   the missing item.

## Mapping table

| Docker secret name | Exported variable | Required |
|--------------------|-------------------|----------|
| `fritzbox_password` | `FRITZBOX_PASSWORD` | yes |
| `carddav_1_password` | `CARDDAV_1_PASSWORD` | per configured source |
| `carddav_<n>_password` | `CARDDAV_<n>_PASSWORD` | per configured source |
| `ftp_password` | `FTP_PASSWORD` | no — FTP reuses the FritzBox web credentials by default; only add this secret when a dedicated FTP user is configured |
| `smtp_password` | `SMTP_PASSWORD` | only if SMTP auth is used |

## Wrapper-only variables (plain env, not secrets)

| Variable | Purpose | Default |
|----------|---------|---------|
| `SMTP_HOST` | mail server for failure notification | — (notifications off when unset) |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_STARTTLS` | use STARTTLS | `true` |
| `SMTP_USERNAME` | SMTP auth username | — |
| `EMAIL_FROM` | sender address | — |
| `EMAIL_TO` | recipient address | — |
| `SYNC_CONFIG` | path to the mounted `config.ini` inside the container | `/config/config.ini` |

## Versioning

Adding/removing a mapping row is a breaking change to operators' deployments
and MUST be reflected in `docker/deploy.sh`, `docker/swarm.md`, and this file
in the same change.
