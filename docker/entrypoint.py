#!/usr/bin/env python3
"""Container entrypoint wrapper for the carddav2fritzbox sync.

Runs the sync as a subprocess, tees its merged stdout/stderr to the
container streams (platform log stays authoritative) while retaining the
output in memory, propagates the child's exit code verbatim, and sends a
single failure email when the sync exits non-zero.

Behavioural contract: specs/002-docker-swarm-deployment/contracts/wrapper.md
Secret-to-environment mapping: contracts/env-secrets.md
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_CONFIG_PATH = "/config/config.ini"
SECRETS_DIR = "/run/secrets"

# Normative mapping: contracts/env-secrets.md
SECRET_MAPPINGS = {
    "fritzbox_password": "FRITZBOX_PASSWORD",
    "ftp_password": "FTP_PASSWORD",
    "smtp_password": "SMTP_PASSWORD",
}
# Numbered CardDAV sources: carddav_<n>_password -> CARDDAV_<n>_PASSWORD


class SecretLoaderError(RuntimeError):
    """A required secret is missing; abort before any network contact (FR-014)."""


def _variable_for_secret(name: str) -> str | None:
    if name in SECRET_MAPPINGS:
        return SECRET_MAPPINGS[name]
    prefix = "carddav_"
    suffix = "_password"
    if name.startswith(prefix) and name.endswith(suffix):
        middle = name[len(prefix) : -len(suffix)]
        if middle.isdigit():
            return f"CARDDAV_{middle}_PASSWORD"
    return None


def load_secrets(
    env: dict[str, str],
    expected: list[str] | None = None,
    secrets_dir: str | None = None,
) -> dict[str, str]:
    """Read mounted secret files and export them as env overrides.

    Only files whose names appear in the contract mapping are consumed;
    anything else under the secrets directory is ignored. Empty or
    unreadable secret files count as absent (existing precedence rule).
    Values never end up in logs or error messages (FR-013).
    """
    base_dir = secrets_dir or SECRETS_DIR
    resolved: dict[str, str] = {}

    try:
        entries = sorted(os.listdir(base_dir))
    except OSError:
        entries = []

    for name in entries:
        variable = _variable_for_secret(name)
        if variable is None:
            continue
        try:
            value = Path(base_dir, name).read_text()
        except OSError:
            continue
        value = value.strip()
        if not value:
            continue
        resolved[variable] = value

    for name in expected or []:
        if _variable_for_secret(name) not in resolved:
            raise SecretLoaderError(
                f"Required Docker secret '{name}' is missing under {base_dir}; "
                "create it with docker secret create before deploying."
            )

    return {**env, **resolved}


@dataclass
class MailSettings:
    """Failure-notification settings (wrapper-only, plain env)."""

    host: str | None
    port: int
    starttls: bool
    username: str | None
    password: str | None
    sender: str | None
    recipient: str | None

    @classmethod
    def from_env(cls, env: dict[str, str]) -> MailSettings:
        return cls(
            host=env.get("SMTP_HOST") or None,
            port=int(env.get("SMTP_PORT") or "587"),
            starttls=(env.get("SMTP_STARTTLS", "true").lower() != "false"),
            username=env.get("SMTP_USERNAME") or None,
            password=env.get("SMTP_PASSWORD") or None,
            sender=env.get("EMAIL_FROM") or None,
            recipient=env.get("EMAIL_TO") or None,
        )

    def is_complete(self) -> bool:
        return bool(self.host and self.sender and self.recipient)


def build_sync_command(env: dict[str, str]) -> list[str]:
    """Build the sync invocation honouring $SYNC_CONFIG."""
    config_path = env.get("SYNC_CONFIG") or DEFAULT_CONFIG_PATH
    return [sys.executable or "python3", "src/main.py", "--config", config_path]


def execute_sync(
    command: list[str],
    sinks: tuple | list = (),
    env: dict[str, str] | None = None,
    python: str | None = None,
) -> tuple[int, str]:
    """Run ``command`` merging stderr into stdout.

    The merged stream is written to every sink (e.g. the real stdout so the
    platform log keeps the full output) and returned as one string together
    with the child's exit code.
    """
    merged_env = {**os.environ, **(env or {})}
    process = subprocess.Popen(  # noqa: S603 - fixed argument vector
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=merged_env,
        executable=python,
        text=True,
        errors="replace",
    )
    chunks: list[str] = []
    assert process.stdout is not None
    with process.stdout:
        for line in iter(process.stdout.readline, ""):
            chunks.append(line)
            for sink in sinks:
                try:
                    sink.write(line)
                    sink.flush()
                except Exception:  # noqa: BLE001 - tee must never break the run
                    pass
    return process.wait(), "".join(chunks)


def main() -> int:
    env = dict(os.environ)
    mail = MailSettings.from_env(env)

    try:
        expected_secrets = [
            name.strip()
            for name in env.get("SYNC_EXPECTED_SECRETS", "").split(",")
            if name.strip()
        ]
        env = load_secrets(env, expected=expected_secrets)
    except SecretLoaderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    command = build_sync_command(env)
    exit_code, output = execute_sync(command, sinks=[sys.stdout])

    if exit_code != 0 and mail.is_complete():
        # Imported lazily so environments without SMTP settings skip the cost.
        import notify

        try:
            notify.send_failure(mail, exit_code, output)
        except Exception as exc:  # noqa: BLE001 - FR-015: never mask the outcome
            print(
                f"ERROR: failure notification could not be sent: {exc}",
                file=sys.stderr,
            )

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
