"""Unit tests for the failure-email sender (T009)."""

import pytest

from docker.entrypoint import MailSettings
from docker.notify import SUBJECT_PREFIX, render_body, send_failure


class FakeSMTP:
    """Records one send_message call; simulates smtplib.SMTP."""

    sent: list = []
    fail_next: Exception | None = None

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.starttls_called = False
        self.logged_in = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.starttls_called = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, message):
        if FakeSMTP.fail_next is not None:
            raise FakeSMTP.fail_next
        FakeSMTP.sent.append(message)


@pytest.fixture()
def fake_smtp(monkeypatch):
    FakeSMTP.sent.clear()
    FakeSMTP.fail_next = None
    monkeypatch.setattr("docker.notify.smtplib.SMTP", FakeSMTP)
    return FakeSMTP


def complete_mail(**overrides):
    values = dict(
        host="smtp.example.com",
        port=587,
        starttls=True,
        username="mailer",
        password="s3cret",
        sender="sync@example.com",
        recipient="admin@example.com",
    )
    values.update(overrides)
    return MailSettings(**values)


def test_render_body_contains_output_and_exit_code():
    body = render_body(4, "boom happened\npartial line")
    assert "boom happened" in body
    assert "Exit code: 4" in body.splitlines()[-1]


def test_failure_sends_exactly_one_email(fake_smtp):
    mail = complete_mail()
    send_failure(mail, exit_code=2, output="something broke")
    assert len(fake_smtp.sent) == 1
    message = fake_smtp.sent[0]
    assert message["To"] == "admin@example.com"
    assert message["From"] == "sync@example.com"


def test_subject_contains_prefix_and_exit_code(fake_smtp):
    send_failure(complete_mail(), exit_code=3, output="x")
    subject = fake_smtp.sent[0]["Subject"]
    assert SUBJECT_PREFIX in subject
    assert "3" in subject


def test_body_carries_full_captured_output(fake_smtp):
    output = "line one\nline two\n"
    send_failure(complete_mail(), exit_code=1, output=output)
    body = fake_smtp.sent[0].get_content()
    assert "line one" in body and "line two" in body


def test_starttls_and_auth_used_when_configured(monkeypatch):
    class Recorder(FakeSMTP):
        instances = []

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            Recorder.instances.append(self)

    monkeypatch.setattr("docker.notify.smtplib.SMTP", Recorder)
    send_failure(complete_mail(), exit_code=1, output="x")
    assert Recorder.instances[0].starttls_called is True
    assert Recorder.instances[0].logged_in == ("mailer", "s3cret")


def test_incomplete_mail_settings_raise(fake_smtp):
    with pytest.raises(ValueError):
        send_failure(complete_mail(host=None), exit_code=1, output="x")
    assert fake_smtp.sent == []


def test_transport_error_raises_for_caller(fake_smtp):
    """FR-015 support: raise so the wrapper can log but keep the exit code."""
    fake_smtp.fail_next = ConnectionRefusedError("smtp down")
    with pytest.raises(ConnectionRefusedError):
        send_failure(complete_mail(), exit_code=1, output="x")
