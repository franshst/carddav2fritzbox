#!/usr/bin/env bash
# Example script: create the Docker secrets for carddav2fritzbox and deploy
# the Swarm stack (FR-009).
#
# Usage:
#   ./deploy.sh                      # interactive: prompts for each secret
#   ./deploy.sh --from-file NAME=PATH [--from-file NAME=PATH ...]
#
# Secret names are normative (specs/002-docker-swarm-deployment/contracts/env-secrets.md):
#   fritzbox_password, carddav_1_password .. carddav_<n>_password,
#   smtp_password (optional)
# No separate FTP secret: the FTP upload reuses the FritzBox web credentials.
#
# No credential values are ever embedded in this script or passed on the
# command line (FR-013). Re-running is idempotent: existing secrets are kept
# unless you answer 'y' when asked to replace them.
#
# Stack configuration (schedule, mail settings, image) comes from the
# environment and is read by docker-compose.yml at deploy time, e.g.:
#   SYNC_CRON="0 4 * * *" SMTP_HOST=smtp.example.com EMAIL_FROM=... \
#   EMAIL_TO=... SYNC_EXPECTED_SECRETS="fritzbox_password" ./deploy.sh

set -euo pipefail

STACK_NAME="${STACK_NAME:-carddav2fritzbox}"
COMPOSE_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/docker-compose.yml"

SECRET_NAMES=(
  fritzbox_password
  carddav_1_password
  carddav_2_password
  carddav_3_password
  smtp_password
)

declare -A FROM_FILE=()

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --from-file)
        shift
        [[ "$1" == *=* ]] || { echo "ERROR: --from-file expects NAME=PATH" >&2; exit 2; }
        FROM_FILE["${1%%=*}"]="${1#*=}"
        ;;
      *)
        echo "ERROR: unknown argument '$1'" >&2
        exit 2
        ;;
    esac
    shift
  done
}

secret_exists() {
  docker secret inspect "$1" >/dev/null 2>&1
}

create_or_update() {
  local name="$1" source="$2"
  if secret_exists "$name"; then
    if [[ "${FORCE_REPLACE:-0}" != "1" ]]; then
      read -r -p "Secret '$name' already exists. Replace? [y/N] " answer
      [[ "${answer:-N}" =~ ^[Yy]$ ]] || { echo "keeping existing '$name'"; return 0; }
    fi
    echo "ERROR: cannot replace in-use secret '$name'; remove it from all services first:" >&2
    echo "  docker stack rm $STACK_NAME && docker secret rm $name" >&2
    return 1
  fi
  docker secret create "$name" "$source" >/dev/null
  echo "created secret '$name'"
}

prompt_secret() {
  local name="$1" tmp
  tmp=$(mktemp)
  chmod 600 "$tmp"
  read -r -s -p "Enter value for secret '$name' (empty to skip): " value
  echo >&2
  printf '%s' "$value" >"$tmp"
  printf '%s' "$tmp"
}

main() {
  parse_args "$@"

  echo "== Creating Docker secrets for stack '$STACK_NAME' =="
  for name in "${SECRET_NAMES[@]}"; do
    if [[ -n "${FROM_FILE[$name]:-}" ]]; then
      create_or_update "$name" "${FROM_FILE[$name]}"
    else
      tmp=$(prompt_secret "$name")
      if [ ! -s "$tmp" ]; then
        rm -f "$tmp"
        echo "skipped '$name' (empty)"
        continue
      fi
      create_or_update "$name" "$tmp"
      rm -f "$tmp"
    fi
  done

  echo
  echo "== Deploying stack =="
  # shellcheck disable=SC2086 - env vars are meant to expand here
  docker stack deploy -c "$COMPOSE_FILE" "$STACK_NAME"
  echo
  echo "Deployed. Check scheduling with:"
  echo "  docker service ls | grep $STACK_NAME"
  echo "  docker service logs ${STACK_NAME}_carddav2fritzbox"
}

main "$@"
