"""Unit tests for FritzBox challenge-response authentication.

Tests the authentication helpers in src/services/fritzbox_uploader.py:
- PBKDF2-HMAC-SHA256 challenge-response (FRITZ!OS 7.24+, research.md 2.1)
- Legacy MD5 challenge-response
- Challenge dispatcher (``2$`` prefix -> PBKDF2, otherwise MD5)
"""

import logging

import pytest
import requests

from src.config.loader import FritzBoxConfig
from src.services.converter import PhoneNumberNormalizer
from src.services.fritzbox_uploader import FritzBoxUploader
from src.models.contact import Contact, PhoneNumber


def _make_uploader(password: str = "1example!") -> FritzBoxUploader:
    """Build a FritzBoxUploader with the given password."""
    config = FritzBoxConfig(
        url="https://fritz.box",
        username="test_user",
        password=password,
        target_book="CardDAV Sync",
    )
    logger = logging.getLogger("test_fritzbox_auth")
    logger.addHandler(logging.NullHandler())
    return FritzBoxUploader(config, logger)


class TestPBKDF2Response:
    """Tests for the PBKDF2-HMAC-SHA256 challenge-response."""

    def test_avm_official_test_vector(self):
        """Test the response matches the AVM session-ID spec test vector."""
        uploader = _make_uploader("1example!")
        challenge = "2$10000$5A1711$2000$5A1722"

        response = uploader._calculate_pbkdf2_response(challenge)

        assert response == (
            "5A1722$" "1798a1672bca7c6463d6b245f82b53703b0f50813401b03e4045a5861e689adb"
        )

    def test_response_is_salt2_hash(self):
        """Test the response has the '<salt2>$<hash>' format."""
        uploader = _make_uploader("password")
        challenge = "2$1000$0A0B$2000$0C0D0E"

        response = uploader._calculate_pbkdf2_response(challenge)

        assert response.startswith("0C0D0E$")
        # 32-byte SHA256 digest -> 64 hex chars after the salt
        assert len(response.split("$", 1)[1]) == 64

    def test_different_password_different_response(self):
        """Test that a different password yields a different response."""
        challenge = "2$10000$5A1711$2000$5A1722"

        uploader_a = _make_uploader("password-a")
        uploader_b = _make_uploader("password-b")

        assert uploader_a._calculate_pbkdf2_response(
            challenge
        ) != uploader_b._calculate_pbkdf2_response(challenge)

    def test_different_challenge_different_response(self):
        """Test that a different challenge yields a different response."""
        uploader = _make_uploader()

        response_a = uploader._calculate_pbkdf2_response("2$1000$AA$1000$BB")
        response_b = uploader._calculate_pbkdf2_response("2$1000$AA$1000$CC")

        assert response_a != response_b

    def test_malformed_challenge_raises_value_error(self):
        """Test that a malformed PBKDF2 challenge raises ValueError."""
        uploader = _make_uploader()

        for malformed in ("2$1000$5A1711", "2$", "2$1000$AA$2000", ""):
            with pytest.raises(ValueError):
                uploader._calculate_pbkdf2_response(malformed)


class TestMD5Response:
    """Tests for the legacy MD5 challenge-response."""

    def test_known_reference_value(self):
        """Test the MD5 response matches a known reference value."""
        uploader = _make_uploader("1example!")

        response = uploader._calculate_md5_response("314159265")

        assert response == "314159265-af859360628e0b6f678aedeb06fc68e7"

    def test_response_format_challenge_md5(self):
        """Test the response has the '<challenge>-<md5_hash>' format."""
        uploader = _make_uploader("some-password")
        challenge = "1234567890"

        response = uploader._calculate_md5_response(challenge)

        assert response.startswith(challenge + "-")
        assert len(response.split("-", 1)[1]) == 32

    def test_different_password_different_response(self):
        """Test that a different password yields a different MD5 hash."""
        challenge = "314159265"

        uploader_a = _make_uploader("password-a")
        uploader_b = _make_uploader("password-b")

        assert uploader_a._calculate_md5_response(
            challenge
        ) != uploader_b._calculate_md5_response(challenge)


class TestChallengeResponseDispatcher:
    """Tests for the challenge-response dispatcher."""

    def test_pbkdf2_prefix_dispatches_to_pbkdf2(self):
        """Test that a '2$' challenge uses the PBKDF2 scheme."""
        uploader = _make_uploader("1example!")
        challenge = "2$10000$5A1711$2000$5A1722"

        response = uploader._calculate_challenge_response(challenge)

        assert response == uploader._calculate_pbkdf2_response(challenge)
        assert response.startswith("5A1722$")

    def test_plain_challenge_dispatches_to_md5(self):
        """Test that a non-'2$' challenge uses the legacy MD5 scheme."""
        uploader = _make_uploader("1example!")
        challenge = "314159265"

        response = uploader._calculate_challenge_response(challenge)

        assert response == uploader._calculate_md5_response(challenge)
        assert response == "314159265-af859360628e0b6f678aedeb06fc68e7"


class TestConnectionProbe:
    """Tests for the reachability probe (test_connection)."""

    def test_zero_sid_is_reachable(self, monkeypatch):
        """A zero SID is a normal pre-auth state, not a connection failure."""
        uploader = _make_uploader()

        def fake_get(url, timeout):
            class FakeResponse:
                content = (
                    b'<?xml version="1.0"?><SessionInfo>'
                    b"<SID>0000000000000000</SID>"
                    b"<Challenge>80c4cd34</Challenge>"
                    b"</SessionInfo>"
                )

                def raise_for_status(self):
                    pass

            return FakeResponse()

        monkeypatch.setattr("src.services.fritzbox_uploader.requests.get", fake_get)

        assert uploader.test_connection() is True

    def test_authenticated_sid_is_reachable(self, monkeypatch):
        """A real SID is reachable too."""
        uploader = _make_uploader()

        def fake_get(url, timeout):
            class FakeResponse:
                content = (
                    b'<?xml version="1.0"?><SessionInfo>'
                    b"<SID>0123456789abcdef</SID>"
                    b"</SessionInfo>"
                )

                def raise_for_status(self):
                    pass

            return FakeResponse()

        monkeypatch.setattr("src.services.fritzbox_uploader.requests.get", fake_get)

        assert uploader.test_connection() is True

    def test_missing_sid_is_unreachable(self, monkeypatch):
        """A response without a SID element indicates a problem."""
        uploader = _make_uploader()

        def fake_get(url, timeout):
            class FakeResponse:
                content = b"<html><body>Error</body></html>"

                def raise_for_status(self):
                    pass

            return FakeResponse()

        monkeypatch.setattr("src.services.fritzbox_uploader.requests.get", fake_get)

        assert uploader.test_connection() is False

    def test_http_error_is_unreachable(self, monkeypatch):
        """A failed request indicates the device is unreachable."""
        uploader = _make_uploader()

        def fake_get(url, timeout):
            raise requests.RequestException("Connection refused")

        monkeypatch.setattr("src.services.fritzbox_uploader.requests.get", fake_get)

        assert uploader.test_connection() is False


class TestPhonebookUpload:
    """Tests for the firmwarecfg phonebook upload response handling."""

    NL_SUCCESS = "<p>Het telefoonboek van de FRITZ!Box is hersteld.</p>"
    DE_SUCCESS = "<p>Das Telefonbuch der FRITZ!Box wurde wiederhergestellt.</p>"
    EN_SUCCESS = "<p>The FRITZ!Box telephone book was restored.</p>"
    NL_ERROR = '<p class="ErrorMsg">Invalid variable name.</p>'

    def _uploader_with(self, monkeypatch, body):
        uploader = _make_uploader()
        uploader.session_id = "0123456789abcdef"

        def fake_post(url, files, timeout):
            class FakeResponse:
                text = body

                def raise_for_status(self):
                    pass

            return FakeResponse()

        monkeypatch.setattr("src.services.fritzbox_uploader.requests.post", fake_post)
        return uploader

    def test_success_dutch(self, monkeypatch):
        """A Dutch success page is recognized as a successful upload."""
        uploader = self._uploader_with(monkeypatch, self.NL_SUCCESS)
        assert uploader._upload_to_fritzbox("<phonebooks/>", "Test", 0) is True

    def test_success_german(self, monkeypatch):
        """A German success page is recognized as a successful upload."""
        uploader = self._uploader_with(monkeypatch, self.DE_SUCCESS)
        assert uploader._upload_to_fritzbox("<phonebooks/>", "Test", 0) is True

    def test_success_english(self, monkeypatch):
        """An English success page is recognized as a successful upload."""
        uploader = self._uploader_with(monkeypatch, self.EN_SUCCESS)
        assert uploader._upload_to_fritzbox("<phonebooks/>", "Test", 0) is True

    def test_error_page_returns_false(self, monkeypatch):
        """A failure page returns False."""
        uploader = self._uploader_with(monkeypatch, self.NL_ERROR)
        assert uploader._upload_to_fritzbox("<phonebooks/>", "Test", 0) is False

    def test_unknown_response_returns_false(self, monkeypatch):
        """An unrecognized response is treated as a failure."""
        uploader = self._uploader_with(monkeypatch, "<html><body>???</body></html>")
        assert uploader._upload_to_fritzbox("<phonebooks/>", "Test", 0) is False

    def test_upload_fields_omit_import_name(self, monkeypatch):
        """The request must not include the unsupported PhonebookImportName."""
        uploader = _make_uploader()
        uploader.session_id = "0123456789abcdef"
        captured = {}

        def fake_post(url, files, timeout):
            captured["fields"] = list(files.keys())
            captured["filename"] = files["PhonebookImportFile"][0]

            class FakeResponse:
                text = "<p>is hersteld.</p>"

                def raise_for_status(self):
                    pass

            return FakeResponse()

        monkeypatch.setattr("src.services.fritzbox_uploader.requests.post", fake_post)

        assert uploader._upload_to_fritzbox("<phonebooks/>", "Test", 0) is True
        assert "PhonebookImportName" not in captured["fields"]
        assert "PhonebookImportFile" in captured["fields"]
        assert captured["filename"] == "updatepb.xml"


class TestTargetBookResolution:
    """Tests for phonebook id resolution honoring target_book (TR-064)."""

    def test_explicit_id_wins(self):
        """An explicit phonebook_id bypasses TR-064 resolution."""
        uploader = _make_uploader()

        class _NeverCalled:
            def resolve_phonebook_id(self, name):
                raise AssertionError("TR-064 must not be called")

        uploader._client = _NeverCalled()

        assert uploader._resolve_phonebook_id(5) == 5

    def test_resolves_by_name_via_tr064(self, monkeypatch):
        """None resolves the configured target_book through TR-064."""
        uploader = _make_uploader()

        class _Stub:
            def __init__(self, *args, **kwargs):
                pass

            def resolve_phonebook_id(self, name):
                assert name == "CardDAV Sync"
                return 2

        monkeypatch.setattr("src.services.fritzbox_uploader.Tr064Client", _Stub)

        assert uploader._resolve_phonebook_id(None) == 2

    def test_falls_back_to_zero_when_tr064_unavailable(self, monkeypatch):
        """An unreachable TR-064 service falls back to the main book (0)."""
        uploader = _make_uploader()

        class _Failing:
            def __init__(self, *args, **kwargs):
                pass

            def resolve_phonebook_id(self, name):
                raise ConnectionError("port closed")

        monkeypatch.setattr("src.services.fritzbox_uploader.Tr064Client", _Failing)

        assert uploader._resolve_phonebook_id(None) == 0

    def test_falls_back_to_zero_when_resolution_fails(self, monkeypatch):
        """A failed resolution (None) falls back to the main book (0)."""
        uploader = _make_uploader()

        class _Stub:
            def __init__(self, *args, **kwargs):
                pass

            def resolve_phonebook_id(self, name):
                return None

        monkeypatch.setattr("src.services.fritzbox_uploader.Tr064Client", _Stub)

        assert uploader._resolve_phonebook_id(None) == 0

    def test_upload_phonebook_uses_resolved_id(self, monkeypatch):
        """upload_phonebook passes the resolved id to the firmwarecfg import."""
        uploader = _make_uploader()
        uploader.session_id = "0123456789abcdef"
        captured = {}

        class _Stub:
            def __init__(self, *args, **kwargs):
                pass

            def resolve_phonebook_id(self, name):
                return 7

        monkeypatch.setattr("src.services.fritzbox_uploader.Tr064Client", _Stub)

        def fake_post(url, files, timeout):
            captured["phonebook_id"] = files["PhonebookId"][1]

            class FakeResponse:
                text = "<p>is hersteld.</p>"

                def raise_for_status(self):
                    pass

            return FakeResponse()

        monkeypatch.setattr("src.services.fritzbox_uploader.requests.post", fake_post)

        contact = Contact(name="John Doe", phone_numbers=[])
        assert uploader.upload_phonebook([contact], "Test", phonebook_id=None) is True
        assert captured["phonebook_id"] == "7"


class TestNumberlessContactFilter:
    """The box silently drops numberless contacts on import; skip them."""

    def test_upload_skips_contact_without_phone(self, monkeypatch):
        uploader = _make_uploader()
        uploader.session_id = "0123456789abcdef"
        captured = {}

        def fake_post(url, files, timeout):
            captured["xml"] = files["PhonebookImportFile"][1].decode("utf-8")

            class FakeResponse:
                text = "<p>is hersteld.</p>"

                def raise_for_status(self):
                    pass

            return FakeResponse()

        monkeypatch.setattr("src.services.fritzbox_uploader.requests.post", fake_post)

        contacts = [
            Contact(name="Has Number", phone_numbers=[PhoneNumber("0201234567")]),
            Contact(name="No Number", phone_numbers=[]),
        ]

        assert uploader.upload_phonebook(contacts, "Test", 0) is True
        assert "No Number" not in captured["xml"]
        assert "Has Number" in captured["xml"]


class TestExportShortening:
    """Tests for FR-006 export-time shortening in the generated XML."""

    def _xml_for(self, uploader, number):
        contact = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number=number, type="home", prio=1)],
        )
        return uploader._generate_phonebook_xml([contact], "Test")

    def test_shortens_local_number_when_normalizer_configured(self):
        """With a normalizer, a local canonical number is shortened (FR-006)."""
        uploader = _make_uploader()
        uploader.normalizer = PhoneNumberNormalizer("+49", "30", "00")
        xml = self._xml_for(uploader, "+4930123456")
        assert "030123456" in xml
        assert "+4930123456" not in xml

    def test_keeps_foreign_number_canonical(self):
        """Foreign numbers stay in canonical form (FR-006)."""
        uploader = _make_uploader()
        uploader.normalizer = PhoneNumberNormalizer("+49", "30", "00")
        xml = self._xml_for(uploader, "+442079460958")
        assert "+442079460958" in xml

    def test_no_normalizer_keeps_canonical(self):
        """Without a normalizer the canonical form is uploaded unchanged."""
        uploader = _make_uploader()
        xml = self._xml_for(uploader, "+4930123456")
        assert "+4930123456" in xml
