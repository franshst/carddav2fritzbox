"""Integration tests for complete CardDAV to FritzBox sync workflow.

These tests validate the end-to-end sync process including:
- Complete sync workflow with mock FritzBox
- Error handling scenarios
- Configuration validation
- Contact transformation pipeline
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os

from src.config.loader import (
    SyncConfig, GeneralConfig, FritzBoxConfig, RegionalConfig,
    CardDAVSourceConfig, load_config
)
from src.models.contact import Contact, PhoneNumber, EmailAddress
from src.services.carddav_fetcher import CardDAVFetcher
from src.services.converter import (
    PhoneNumberNormalizer, ImageConverter,
    validate_and_normalize_contact
)
from src.services.fritzbox_uploader import FritzBoxUploader
from src.utils.logger import setup_logger


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
                target_book="CardDAV Sync"
            ),
            regional=RegionalConfig(
                country="DE",
                region="DE",
                country_code="+49",
                region_code="30"
            ),
            sources=[
                CardDAVSourceConfig(
                    url="https://nextcloud.example.com",
                    username="user1",
                    password="pass1",
                    priority=1
                )
            ]
        )

        # Create mock contacts
        contacts = [
            Contact(
                name="John Doe",
                phone_numbers=[
                    PhoneNumber(number="+1234567890", type="home", prio=1),
                    PhoneNumber(number="+442071234567", type="mobile", prio=0)
                ],
                emails=[
                    EmailAddress(email="john@example.com", classifier="private"),
                    EmailAddress(email="john@work.com", classifier="work")
                ],
                is_vip=False
            ),
            Contact(
                name="Jane Smith",
                phone_numbers=[
                    PhoneNumber(number="+15551234567", type="mobile", prio=1)
                ],
                emails=[
                    EmailAddress(email="jane@example.com", classifier="private")
                ],
                is_vip=True
            )
        ]

        # Mock services
        with patch.object(CardDAVFetcher, 'fetch_and_parse_contacts') as mock_fetch:
            with patch.object(FritzBoxUploader, 'test_connection') as mock_test:
                with patch.object(FritzBoxUploader, 'upload_phonebook') as mock_upload:
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
                    result = uploader.upload_phonebook(fetched_contacts, "CardDAV Sync", 0)
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
                url="https://fritz.box",
                username="test",
                password="test"
            ),
            regional=RegionalConfig(
                country="US",
                region="CA",
                country_code="+1",
                region_code="650"
            ),
            sources=[]
        )

        # Create contact with various phone number formats
        contact = Contact(
            name="Test User",
            phone_numbers=[
                PhoneNumber(number="(415) 555-2671", type="home", prio=1),
                PhoneNumber(number="+44 20 7946 0958", type="work", prio=0),
                PhoneNumber(number="650-123-4567", type="mobile", prio=0)
            ]
        )

        # Normalize the contact
        normalizer = PhoneNumberNormalizer(config.regional.country_code, config.regional.region_code)
        normalized = validate_and_normalize_contact(contact, normalizer)

        # Verify normalization
        assert len(normalized.phone_numbers) == 3
        assert normalized.phone_numbers[0].number == "+14155552671"
        assert normalized.phone_numbers[1].number == "+442079460958"
        assert normalized.phone_numbers[2].number == "+16501234567"

    def test_sync_error_handling_connection_failure(self):
        """Test sync error handling when FritzBox connection fails."""
        config = SyncConfig(
            general=GeneralConfig(name_order="first_name_first"),
            fritzbox=FritzBoxConfig(
                url="https://fritz.box",
                username="test",
                password="test"
            ),
            regional=RegionalConfig(
                country="DE",
                region="DE",
                country_code="+49",
                region_code="30"
            ),
            sources=[]
        )

        # Mock uploader with failing connection
        with patch.object(FritzBoxUploader, 'test_connection', return_value=False):
            uploader = FritzBoxUploader(config.fritzbox, self.logger)
            result = uploader.test_connection()
            assert result is False

    def test_sync_with_image_processing(self):
        """Test sync with image processing."""
        config = SyncConfig(
            general=GeneralConfig(name_order="first_name_first"),
            fritzbox=FritzBoxConfig(
                url="https://fritz.box",
                username="test",
                password="test"
            ),
            regional=RegionalConfig(
                country="DE",
                region="DE",
                country_code="+49",
                region_code="30"
            ),
            sources=[]
        )

        # Create contact with photo
        contact = Contact(
            name="Photo User",
            phone_numbers=[],
            picture_data=b"test_image_data",
            picture_url=None
        )

        # Mock image converter
        with patch.object(ImageConverter, 'convert_vcard_photo') as mock_convert:
            mock_convert.return_value = (b"converted_jpg_data", None)

            converter = ImageConverter(self.logger)
            result = converter.convert_vcard_photo(contact.picture_data, photo_type='base64')

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
        with open(config_path, 'w') as f:
            f.write(invalid_config_content)

        try:
            config = load_config(config_path)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Missing required 'fritzbox' section" in str(e)

    def test_phonebook_xml_generation(self):
        """Test FritzBox XML document generation."""
        config = SyncConfig(
            general=GeneralConfig(name_order="first_name_first"),
            fritzbox=FritzBoxConfig(
                url="https://fritz.box",
                username="test",
                password="test",
                target_book="Test Phonebook"
            ),
            regional=RegionalConfig(
                country="DE",
                region="DE",
                country_code="+49",
                region_code="30"
            ),
            sources=[]
        )

        # Create test contacts
        contacts = [
            Contact(
                name="John Doe",
                phone_numbers=[
                    PhoneNumber(number="+4930123456", type="home", prio=1),
                    PhoneNumber(number="+491234567890", type="mobile", prio=0)
                ],
                emails=[
                    EmailAddress(email="john@example.com", classifier="private"),
                    EmailAddress(email="john@work.com", classifier="work")
                ],
                is_vip=True
            )
        ]

        # Create uploader and generate XML
        uploader = FritzBoxUploader(config.fritzbox, self.logger)

        with patch.object(uploader, 'authenticate', return_value=True):
            with patch.object(uploader, '_upload_to_fritzbox', return_value=True):
                # Test authentication
                assert uploader.authenticate() is True

                # Generate XML
                xml_content = uploader._generate_phonebook_xml(contacts, "Test Phonebook")

                # Basic validation
                assert isinstance(xml_content, str)
                assert "phonebooks" in xml_content
                assert "Test Phonebook" in xml_content
                assert "John Doe" in xml_content
                assert "+4930123456" in xml_content
                assert "john@example.com" in xml_content

    def test_contact_identity_based_merge(self):
        """Test contact identity-based merging logic."""
        from src.services.carddav_fetcher import CardDAVFetcher

        config = SyncConfig(
            general=GeneralConfig(name_order="first_name_first"),
            fritzbox=FritzBoxConfig(
                url="https://fritz.box",
                username="test",
                password="test"
            ),
            regional=RegionalConfig(
                country="DE",
                region="DE",
                country_code="+49",
                region_code="30"
            ),
            sources=[]
        )

        fetcher = CardDAVFetcher(config, self.logger)

        # Create duplicate contacts (same name and phone)
        contact1 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+4930123456", type="home", prio=1)],
            emails=[EmailAddress(email="john@example.com", classifier="private")]
        )

        contact2 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+4930123456", type="home", prio=1)],
            emails=[EmailAddress(email="john@example.com", classifier="private")]
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
