"""Unit tests for CLI exit codes (contracts/cli.md)."""

import logging
from unittest.mock import patch

from src.config.loader import (
    CardDAVSourceConfig,
    FritzBoxConfig,
    GeneralConfig,
    RegionalConfig,
    SyncConfig,
)
from src.main import parse_arguments, run_sync
from src.models.contact import Contact, PhoneNumber


def _config() -> SyncConfig:
    return SyncConfig(
        general=GeneralConfig(name_order="first_name_first"),
        fritzbox=FritzBoxConfig(url="https://fritz.box", username="u", password="p"),
        regional=RegionalConfig(
            country="DE", region="DE", country_code="+49", area_code="30"
        ),
        sources=[
            CardDAVSourceConfig(
                url="https://dav", username="u", password="p", priority=1
            )
        ],
    )


def _contact() -> Contact:
    return Contact(name="A", phone_numbers=[PhoneNumber("030123456")])


def test_connection_error_returns_2():
    """A FritzBox connection failure exits with code 2."""
    with patch("src.main.FritzBoxUploader.test_connection", return_value=False):
        assert run_sync(_config()) == 2


def test_sync_error_returns_3():
    """A failed upload exits with code 3."""
    with (
        patch("src.main.FritzBoxUploader.test_connection", return_value=True),
        patch(
            "src.main.CardDAVFetcher.fetch_and_parse_contacts",
            return_value=[_contact()],
        ),
        patch("src.main.FritzBoxUploader.upload_phonebook", return_value=False),
    ):
        assert run_sync(_config()) == 3


def test_success_returns_0():
    """A successful sync exits with code 0."""
    with (
        patch("src.main.FritzBoxUploader.test_connection", return_value=True),
        patch(
            "src.main.CardDAVFetcher.fetch_and_parse_contacts",
            return_value=[_contact()],
        ),
        patch("src.main.FritzBoxUploader.upload_phonebook", return_value=True),
    ):
        assert run_sync(_config()) == 0


def test_unexpected_error_returns_4():
    """An unexpected error exits with code 4."""
    with patch(
        "src.main.FritzBoxUploader.test_connection",
        side_effect=RuntimeError("boom"),
    ):
        assert run_sync(_config()) == 4


class TestDefaultLogLevel:
    """The default log level is WARNING so the program runs silently (FR-008)."""

    def test_parse_arguments_default_is_warning(self, monkeypatch):
        """`--log-level` defaults to WARNING when omitted."""
        monkeypatch.setattr("sys.argv", ["prog", "--config", "x.ini"])
        args = parse_arguments()
        assert args.log_level == "WARNING"

    def test_run_sync_default_logger_is_warning(self):
        """run_sync configures its logger at WARNING unless told otherwise."""
        with patch("src.main.FritzBoxUploader.test_connection", return_value=False):
            run_sync(_config())
        logger = logging.getLogger("carddav_sync")
        assert logger.level == logging.WARNING

    def test_run_sync_respects_explicit_log_level(self):
        """An explicit log_level is applied to the run_sync logger."""
        with patch("src.main.FritzBoxUploader.test_connection", return_value=False):
            run_sync(_config(), log_level="DEBUG")
        logger = logging.getLogger("carddav_sync")
        assert logger.level == logging.DEBUG
