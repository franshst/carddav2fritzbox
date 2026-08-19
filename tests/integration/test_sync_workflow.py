"""Integration tests for complete CardDAV to FritzBox sync workflow.

These tests validate the end-to-end sync process including:
- Complete sync workflow with mock FritzBox
- Real RFC 6352 fetch against a mocked CardDAV HTTP server
- Merge by source priority, normalization, and FritzBox XML generation
- Error handling scenarios
- Configuration validation
- Contact transformation pipeline
"""

import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest

from src.config.loader import (
    SyncConfig,
    GeneralConfig,
    FritzBoxConfig,
    RegionalConfig,
    CardDAVSourceConfig,
    load_config,
)
from src.models.contact import Contact, PhoneNumber, EmailAddress
from src.services.carddav_fetcher import CardDAVFetcher
from src.services.converter import (
    PhoneNumberNormalizer,
    ImageConverter,
    validate_and_normalize_contact,
)
from src.services.fritzbox_uploader import FritzBoxUploader
from src.utils.logger import setup_logger

_DAV_NS = "DAV:"
_CARDDAV_NS = "urn:ietf:params:xml:ns:carddav"


class MockCardDAVHandler(BaseHTTPRequestHandler):
    """Minimal RFC 6352 CardDAV endpoint for integration testing.

    Serves a ``.well-known/carddav`` redirect, a Depth-1 PROPFIND listing a
    CardDAV address book, and a REPORT ``addressbook-query`` returning the
    configured vCards as ``address-data``.
    """

    vcards = []
    expected_auth = None

    def log_message(self, format, *args):
        pass

    def _check_auth(self) -> bool:
        """Verify basic auth against expected credentials (if configured)."""
        if self.expected_auth is None:
            return True
        import base64

        expected = base64.b64encode(
            f"{self.expected_auth[0]}:{self.expected_auth[1]}".encode()
        ).decode()
        if self.headers.get("Authorization") == f"Basic {expected}":
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="CardDAV"')
        self.end_headers()
        return False

    def _send_xml(self, body: bytes):
        self.send_response(207)
        self.send_header("Content-Type", "application/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/.well-known/carddav"):
            self.send_response(302)
            self.send_header("Location", "/remote.php/dav/addressbooks/user/contacts/")
            self.end_headers()
            return
        if self.path.startswith("/remote.php/dav/addressbooks/user/contacts/"):
            # Final redirect target of the .well-known lookup
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_PROPFIND(self):
        if not self._check_auth():
            return
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<d:multistatus xmlns:d="{_DAV_NS}">'
            "<d:response>"
            "<d:href>/remote.php/dav/addressbooks/user/contacts/</d:href>"
            "<d:propstat><d:prop><d:resourcetype><d:collection/>"
            "</d:resourcetype></d:prop><d:status>HTTP/1.1 200 OK</d:status>"
            "</d:propstat>"
            "</d:response>"
            "<d:response>"
            "<d:href>/remote.php/dav/addressbooks/user/contacts/</d:href>"
            f"<d:propstat><d:prop><d:resourcetype><d:collection/>"
            f'<card:addressbook xmlns:card="{_CARDDAV_NS}"/>'
            f"</d:resourcetype></d:prop><d:status>HTTP/1.1 200 OK</d:status>"
            "</d:propstat>"
            "</d:response>"
            "</d:multistatus>"
        ).encode()
        self._send_xml(body)

    def do_REPORT(self):
        if not self._check_auth():
            return
        responses = []
        for i, card in enumerate(self.vcards):
            responses.append(
                "<d:response>"
                "<d:href>/remote.php/dav/addressbooks/user/contacts/"
                f"{i}.vcf</d:href>"
                "<d:propstat><d:prop>"
                '<d:getetag>"abc123"</d:getetag>'
                f"<card:address-data>{card}</card:address-data>"
                "</d:prop><d:status>HTTP/1.1 200 OK</d:status>"
                "</d:propstat>"
                "</d:response>"
            )
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<d:multistatus xmlns:d="{_DAV_NS}" '
            f'xmlns:card="{_CARDDAV_NS}">' + "".join(responses) + "</d:multistatus>"
        ).encode()
        self._send_xml(body)


def _start_mock_dav(vcards, username, password):
    """Start a mock CardDAV server on an ephemeral port and return it."""
    handler = type(
        "MockCardDAVHandler",
        (MockCardDAVHandler,),
        {"vcards": vcards, "expected_auth": (username, password)},
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


VCARD_JOHN_SOURCE1 = """BEGIN:VCARD
VERSION:3.0
UID:contact-john
FN:John Doe
N:Doe;John;;;
TEL;TYPE=home:030-1234567
EMAIL;TYPE=private:john@example.com
END:VCARD"""

VCARD_JOHN_SOURCE2 = """BEGIN:VCARD
VERSION:3.0
UID:contact-john
FN:John Doe
N:Doe;John;;;
TEL;TYPE=home:+49 30 1234567
TEL;TYPE=mobile:+1 415 555-2671
EMAIL;TYPE=private:john@example.com
EMAIL;TYPE=work:john@work.com
END:VCARD"""

VCARD_ALICE = """BEGIN:VCARD
VERSION:3.0
UID:contact-alice
FN:Alice Wonder
N:Wonder;Alice;;;
TEL;TYPE=mobile:+49 151 2345 6789
EMAIL;TYPE=private:alice@example.com
END:VCARD"""

VCARD_BOB = """BEGIN:VCARD
VERSION:3.0
UID:contact-bob
FN:Bob Builder
N:Builder;Bob;;;
TEL;TYPE=home:0228-123456
END:VCARD"""


class TestSyncWorkflow:
    """Test complete sync workflow scenarios."""

    def setup_method(self):
        """Set up test fixtures."""
        self.logger = setup_logger("test_sync_workflow")
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_complete_sync_workflow_with_mock_data(self):
        """Test complete sync workflow with mock CardDAV data."""
        # Create test configuration
        config = SyncConfig(
            general=GeneralConfig(name_order="first_name_first"),
            fritzbox=FritzBoxConfig(
                url="https://fritz.box",
                username="test_user",
                password="test_password",
                target_book="CardDAV Sync",
            ),
            regional=RegionalConfig(
                country="DE", region="DE", country_code="+49", area_code="30"
            ),
            sources=[
                CardDAVSourceConfig(
                    url="https://nextcloud.example.com",
                    username="user1",
                    password="pass1",
                    priority=1,
                )
            ],
        )

        # Create mock contacts
        contacts = [
            Contact(
                name="John Doe",
                phone_numbers=[
                    PhoneNumber(number="+1234567890", type="home", prio=1),
                    PhoneNumber(number="+442071234567", type="mobile", prio=0),
                ],
                emails=[
                    EmailAddress(email="john@example.com", classifier="private"),
                    EmailAddress(email="john@work.com", classifier="work"),
                ],
                is_vip=False,
            ),
            Contact(
                name="Jane Smith",
                phone_numbers=[
                    PhoneNumber(number="+15551234567", type="mobile", prio=1)
                ],
                emails=[EmailAddress(email="jane@example.com", classifier="private")],
                is_vip=True,
            ),
        ]

        # Mock services
        with patch.object(CardDAVFetcher, "fetch_and_parse_contacts") as mock_fetch:
            with patch.object(FritzBoxUploader, "test_connection") as mock_test:
                with patch.object(FritzBoxUploader, "upload_phonebook") as mock_upload:
                    # Setup mock returns
                    mock_fetch.return_value = contacts
                    mock_test.return_value = True
                    mock_upload.return_value = True

                    # Run sync workflow
                    fetcher = CardDAVFetcher(config, self.logger)
                    uploader = FritzBoxUploader(config.fritzbox, self.logger)

                    # Fetch contacts
                    fetched_contacts = fetcher.fetch_and_parse_contacts()
                    assert len(fetched_contacts) == 2
                    assert fetched_contacts[0].name == "John Doe"

                    # Test FritzBox connection
                    assert uploader.test_connection() is True

                    # Upload contacts
                    result = uploader.upload_phonebook(
                        fetched_contacts, "CardDAV Sync", 0
                    )
                    assert result is True

                    # Verify mocks were called
                    mock_fetch.assert_called_once()
                    mock_test.assert_called_once()
                    mock_upload.assert_called_once()

    def test_sync_with_phone_number_normalization(self):
        """Test sync with phone number normalization."""
        config = SyncConfig(
            general=GeneralConfig(name_order="first_name_first"),
            fritzbox=FritzBoxConfig(
                url="https://fritz.box", username="test", password="test"
            ),
            regional=RegionalConfig(
                country="US", region="CA", country_code="+1", area_code="650"
            ),
            sources=[],
        )

        # Create contact with various phone number formats
        contact = Contact(
            name="Test User",
            phone_numbers=[
                PhoneNumber(number="(415) 555-2671", type="home", prio=1),
                PhoneNumber(number="+44 20 7946 0958", type="work", prio=0),
                PhoneNumber(number="6501234567", type="mobile", prio=0),
            ],
        )

        # Normalize the contact (canonical form, FR-005)
        normalizer = PhoneNumberNormalizer(
            config.regional.country_code, config.regional.area_code
        )
        normalized = validate_and_normalize_contact(contact, normalizer)

        # Verify normalization to canonical form
        assert len(normalized.phone_numbers) == 3
        assert normalized.phone_numbers[0].number == "+16504155552671"
        assert normalized.phone_numbers[1].number == "+442079460958"
        assert normalized.phone_numbers[2].number == "+16506501234567"

    def test_sync_error_handling_connection_failure(self):
        """Test sync error handling when FritzBox connection fails."""
        config = SyncConfig(
            general=GeneralConfig(name_order="first_name_first"),
            fritzbox=FritzBoxConfig(
                url="https://fritz.box", username="test", password="test"
            ),
            regional=RegionalConfig(
                country="DE", region="DE", country_code="+49", area_code="30"
            ),
            sources=[],
        )

        # Mock uploader with failing connection
        with patch.object(FritzBoxUploader, "test_connection", return_value=False):
            uploader = FritzBoxUploader(config.fritzbox, self.logger)
            result = uploader.test_connection()
            assert result is False

    def test_sync_with_image_processing(self):
        """Test sync with image processing."""
        # Create contact with photo
        contact = Contact(
            name="Photo User",
            phone_numbers=[],
            picture_data=b"test_image_data",
            picture_url=None,
        )

        # Mock image converter
        with patch.object(ImageConverter, "convert_vcard_photo") as mock_convert:
            mock_convert.return_value = (b"converted_jpg_data", None)

            converter = ImageConverter(self.logger)
            result = converter.convert_vcard_photo(
                contact.picture_data, photo_type="base64"
            )

            assert result[0] == b"converted_jpg_data"

    def test_configuration_validation_error(self):
        """Test configuration validation error handling."""
        # Test with missing required sections
        invalid_config_content = """
[general]
name_order = first_name_first

# Missing fritzbox section
"""

        config_path = os.path.join(self.temp_dir, "invalid_config.ini")
        with open(config_path, "w") as f:
            f.write(invalid_config_content)

        try:
            load_config(config_path)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Missing required 'fritzbox' section" in str(e)

    def test_end_to_end_fetch_merge_normalize_xml(self):
        """Fetch from a real (mocked HTTP) CardDAV server, merge by priority,
        normalize, and produce the FritzBox XML phonebook."""
        server1, url1 = _start_mock_dav(
            [VCARD_JOHN_SOURCE1, VCARD_ALICE], "user1", "pass1"
        )
        server2, url2 = _start_mock_dav(
            [VCARD_JOHN_SOURCE2, VCARD_BOB], "user2", "pass2"
        )
        try:
            config = SyncConfig(
                general=GeneralConfig(name_order="first_name_first"),
                fritzbox=FritzBoxConfig(
                    url="https://fritz.box",
                    username="test",
                    password="test",
                    target_book="CardDAV Sync",
                ),
                regional=RegionalConfig(
                    country="DE",
                    region="DE",
                    country_code="+49",
                    area_code="30",
                    international_access_code="00",
                ),
                sources=[
                    CardDAVSourceConfig(
                        url=url1, username="user1", password="pass1", priority=1
                    ),
                    CardDAVSourceConfig(
                        url=url2, username="user2", password="pass2", priority=2
                    ),
                ],
            )

            # Fetch over the real RFC 6352 flow (.well-known -> PROPFIND -> REPORT)
            fetcher = CardDAVFetcher(config, self.logger)
            fetched = fetcher.fetch_and_parse_contacts()
            assert len(fetched) == 4

            # Merge by priority (FR-004/FR-013): sources are fetched in priority
            # order, so the first encounter of an identity wins; multi-value
            # fields from later sources are appended.
            merged = []
            for contact in fetched:
                existing_idx = next(
                    (
                        i
                        for i, existing in enumerate(merged)
                        if existing.is_duplicate_of(
                            contact, "first_name_first", "+49", "30", "00"
                        )
                    ),
                    None,
                )
                if existing_idx is None:
                    merged.append(contact)
                else:
                    merged[existing_idx].merge_with(contact)

            assert len(merged) == 3

            # The priority-1 John Doe contact now carries source-2's extra
            # fields (FR-004 appends multi-value fields without dedup)
            john = next(c for c in merged if c.name == "John Doe")
            assert len(john.phone_numbers) == 3
            assert len(john.emails) == 3
            assert {e.email for e in john.emails} == {
                "john@example.com",
                "john@work.com",
            }

            # Normalize to canonical form (FR-005)
            normalizer = PhoneNumberNormalizer("+49", "30", "00")
            normalized = [
                validate_and_normalize_contact(contact, normalizer)
                for contact in merged
            ]
            john_norm = next(c for c in normalized if c.name == "John Doe")
            assert sorted(p.number for p in john_norm.phone_numbers) == [
                "+14155552671",
                "+49301234567",
                "+49301234567",
            ]

            # Produce the FritzBox XML phonebook
            uploader = FritzBoxUploader(config.fritzbox, self.logger)
            xml_content = uploader._generate_phonebook_xml(normalized, "CardDAV Sync")

            assert "John Doe" in xml_content
            assert "Alice Wonder" in xml_content
            assert "Bob Builder" in xml_content
            assert "+49301234567" in xml_content
            assert "john@work.com" in xml_content
            assert "CardDAV Sync" in xml_content
        finally:
            server1.shutdown()
            server2.shutdown()
            server1.server_close()
            server2.server_close()

    def test_phonebook_xml_generation(self):
        """Test FritzBox XML document generation."""
        config = SyncConfig(
            general=GeneralConfig(name_order="first_name_first"),
            fritzbox=FritzBoxConfig(
                url="https://fritz.box",
                username="test",
                password="test",
                target_book="Test Phonebook",
            ),
            regional=RegionalConfig(
                country="DE", region="DE", country_code="+49", area_code="30"
            ),
            sources=[],
        )

        # Create test contacts
        contacts = [
            Contact(
                name="John Doe",
                phone_numbers=[
                    PhoneNumber(number="+4930123456", type="home", prio=1),
                    PhoneNumber(number="+491234567890", type="mobile", prio=0),
                ],
                emails=[
                    EmailAddress(email="john@example.com", classifier="private"),
                    EmailAddress(email="john@work.com", classifier="work"),
                ],
                is_vip=True,
            )
        ]

        # Create uploader and generate XML
        uploader = FritzBoxUploader(config.fritzbox, self.logger)

        with patch.object(uploader, "authenticate", return_value=True):
            with patch.object(uploader, "_upload_to_fritzbox", return_value=True):
                # Test authentication
                assert uploader.authenticate() is True

                # Generate XML
                xml_content = uploader._generate_phonebook_xml(
                    contacts, "Test Phonebook"
                )

                # Basic validation
                assert isinstance(xml_content, str)
                assert "phonebooks" in xml_content
                assert "Test Phonebook" in xml_content
                assert "John Doe" in xml_content
                assert "+4930123456" in xml_content
                assert "john@example.com" in xml_content

    def test_contact_identity_based_merge(self):
        """Test contact identity-based merging logic."""
        # Create duplicate contacts (same name and phone)
        contact1 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+4930123456", type="home", prio=1)],
            emails=[EmailAddress(email="john@example.com", classifier="private")],
        )

        contact2 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+4930123456", type="home", prio=1)],
            emails=[EmailAddress(email="john@example.com", classifier="private")],
        )

        # Test duplicate detection
        is_duplicate = contact1.is_duplicate_of(contact2, "first_name_first")
        assert is_duplicate is True

        # Test merging
        merged = contact1.merge_with(contact2)
        assert len(merged.phone_numbers) == 2  # Both phones from contact2 added
        assert len(merged.emails) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
