"""Unit tests for CLI exit codes (contracts/cli.md)."""

from unittest.mock import patch

from src.config.loader import (
    CardDAVSourceConfig,
    FritzBoxConfig,
    GeneralConfig,
    RegionalConfig,
    SyncConfig,
)
from src.main import run_sync
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
