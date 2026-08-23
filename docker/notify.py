#!/usr/bin/env python3
"""Failure-email sender for the carddav2fritzbox container wrapper.

Standard-library only (smtplib/email). Raises on delivery errors so the
caller decides handling (FR-015: notification failure must never mask the
sync outcome).
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from entrypoint import MailSettings

SUBJECT_PREFIX = "carddav2fritzbox sync failed"


def render_body(exit_code: int, output: str) -> str:
    """Full captured output plus a final exit-code line."""
    return f"{output.rstrip()}\n\nExit code: {exit_code}\n"


def send_failure(mail: MailSettings, exit_code: int, output: str) -> None:
    """Send exactly one failure email. Raises on any transport error."""
    if not mail.is_complete():
        raise ValueError("mail settings incomplete; refusing to send")

    message = EmailMessage()
    message["From"] = mail.sender or ""
    message["To"] = mail.recipient or ""
    message["Subject"] = f"{SUBJECT_PREFIX} (exit code {exit_code})"
    message.set_content(render_body(exit_code, output))

    with smtplib.SMTP(mail.host or "", mail.port, timeout=60) as smtp:
        if mail.starttls:
            smtp.starttls()
        if mail.username and mail.password:
            smtp.login(mail.username, mail.password)
        smtp.send_message(message)
