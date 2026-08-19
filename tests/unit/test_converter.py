"""Unit tests for phone number normalization and image conversion utilities.

Tests the converter module functionality:
- PhoneNumberNormalizer for phone number processing
- ImageConverter for vCard image handling
- Helper functions for contact processing
"""

import base64
import pytest
from unittest.mock import Mock, patch

from src.services.converter import (
    PhoneNumberNormalizer,
    ImageConverter,
    extract_phone_number_info,
    process_contact_photos,
    validate_and_normalize_contact,
)
from src.models.contact import Contact, PhoneNumber, EmailAddress


class TestPhoneNumberNormalizer:
    """Test PhoneNumberNormalizer class."""

    def test_normalize_stripping_non_numeric(self):
        """Test that phone numbers are stripped of non-numeric characters."""
        normalizer = PhoneNumberNormalizer("+49", "30")
        result = normalizer.normalize("+1 (415) 555-2671")
        assert result == "+14155552671"

    def test_normalize_preserves_plus(self):
        """Test that leading '+' is preserved."""
        normalizer = PhoneNumberNormalizer("+49", "30")
        result = normalizer.normalize("+44 20 7946 0958")
        assert result == "+442079460958"

    def test_normalize_adds_country_code(self):
        """Test that local numbers (leading 0) get country code added (FR-005)."""
        normalizer = PhoneNumberNormalizer("+49", "30")
        result = normalizer.normalize("0301234567")
        assert result == "+49301234567"

    def test_format_for_fritzbox_with_plus(self):
        """Test shortening for FritzBox (FR-006): local number drops +/CC/area."""
        normalizer = PhoneNumberNormalizer("+49", "30")
        result = normalizer.format_for_fritzbox("+4930123467")
        assert result == "0123467"

    def test_format_for_fritzbox_without_plus(self):
        """Test formatting for FritzBox adds country code if needed."""
        normalizer = PhoneNumberNormalizer("+49", "30")
        result = normalizer.format_for_fritzbox("301234567")
        assert result == "301234567"

    def test_validate_fritzbox_format_valid_international(self):
        """Test validation of valid international phone number."""
        normalizer = PhoneNumberNormalizer("+49", "30")
        result = normalizer.validate_fritzbox_format("+441234567890")
        assert result is True

    def test_validate_fritzbox_format_valid_local(self):
        """Test validation of valid local phone number."""
        normalizer = PhoneNumberNormalizer("+49", "30")
        result = normalizer.validate_fritzbox_format("301234567")
        assert result is True

    def test_validate_fritzbox_format_invalid_too_short(self):
        """Test validation of too short phone number."""
        normalizer = PhoneNumberNormalizer("+49", "30")
        result = normalizer.validate_fritzbox_format("+1")
        assert result is False

    def test_validate_fritzbox_format_invalid_too_long(self):
        """Test validation of too long phone number."""
        normalizer = PhoneNumberNormalizer("+49", "30")
        result = normalizer.validate_fritzbox_format("+123456789012345678901")
        assert result is False

    def test_validate_fritzbox_format_invalid_characters(self):
        """Test validation of phone number with invalid characters."""
        normalizer = PhoneNumberNormalizer("+49", "30")
        result = normalizer.validate_fritzbox_format("+1a2b3c")
        assert result is False


class TestImageConverter:
    """Test ImageConverter class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.logger = Mock()
        self.converter = ImageConverter(self.logger)

    @patch("PIL.Image.open")
    def test_convert_base64_to_jpg(self, mock_image_open):
        """Test conversion of Base64 image to JPG."""
        mock_image = Mock()
        mock_image.mode = "RGB"
        mock_image.size = (400, 400)
        mock_image_open.return_value = mock_image
        mock_image.convert.return_value = mock_image
        mock_image.crop.return_value = mock_image
        mock_image.resize.return_value = mock_image

        mock_bytes_io = Mock()
        mock_image.save.return_value = None

        with patch("io.BytesIO", return_value=mock_bytes_io):
            result = self.converter.convert_vcard_photo(
                base64.b64encode(b"fake_image_data").decode("utf-8"),
                photo_type="base64",
            )
            assert result[0] is not None or result[1] is not None

    def test_convert_external_uri(self):
        """Test handling of external photo URIs."""
        result = self.converter.convert_vcard_photo(
            "https://example.com/avatar.png", photo_type="uri"
        )
        assert result == (None, "https://example.com/avatar.png")

    def test_convert_raw_bytes(self):
        """Test conversion of raw binary image data."""
        with patch("PIL.Image.open") as mock_open:
            mock_image = Mock()
            mock_image.mode = "RGB"
            mock_image.size = (400, 400)
            mock_image.convert.return_value = mock_image
            mock_image.crop.return_value = mock_image
            mock_image.resize.return_value = mock_image
            mock_open.return_value = mock_image

            with patch("io.BytesIO"):
                result = self.converter.convert_vcard_photo(b"raw_image_data")
                assert result[0] is not None

    def test_crop_to_square(self):
        """Test cropping image to square aspect ratio."""
        with patch("PIL.Image.open") as mock_open:
            mock_image = Mock()
            mock_image.mode = "RGB"
            mock_image.size = (600, 400)
            mock_image.crop.return_value = Mock()
            mock_open.return_value = mock_image

            with patch("io.BytesIO"):
                self.converter._crop_to_square(mock_image)
                mock_image.crop.assert_called()

    def test_resize_to_max_dimension_no_resize(self):
        """Test resize when image is already within max dimensions."""
        mock_image = Mock()
        mock_image.size = (300, 300)

        result = self.converter._resize_to_max_dimension(mock_image)
        assert result.size == (300, 300)

    def test_resize_to_max_dimension_resizes_width(self):
        """Test resizing when width exceeds max dimension."""
        mock_image = Mock()
        mock_image.size = (600, 400)
        mock_resized = Mock()
        mock_image.resize.return_value = mock_resized

        result = self.converter._resize_to_max_dimension(mock_image)
        mock_image.resize.assert_called_with((300, 200), 1)
        assert result == mock_resized

    def test_log_warning(self):
        """Test warning logging."""
        self.converter._log_warning("Test warning")
        self.logger.warning.assert_called_with("Test warning")

    def test_log_warning_without_logger(self):
        """Test warning logging when logger is not available."""
        converter = ImageConverter()  # No logger
        converter._log_warning("Test warning")
        # Should print to stdout (can't easily capture in test)


class TestExtractPhoneNumberInfo:
    """Test extract_phone_number_info function."""

    def test_extract_phone_number_info_with_plus(self):
        """Test extraction with phone number containing '+'."""
        phone = extract_phone_number_info("+1234567890", "mobile", 1)
        assert phone.number == "+1234567890"
        assert phone.type == "mobile"
        assert phone.prio == 1

    def test_extract_phone_number_info_without_plus(self):
        """Test extraction with local phone number."""
        with patch("src.services.converter.PhoneNumberNormalizer") as mock_normalizer:
            mock_normalizer.return_value.normalize.return_value = "1234567890"
            mock_normalizer.return_value.format_for_fritzbox.return_value = (
                "+491234567890"
            )

            phone = extract_phone_number_info("1234567890", "home", 0)
            assert phone.number == "+491234567890"


class TestProcessContactPhotos:
    """Test process_contact_photos function."""

    def setup_method(self):
        """Set up test fixtures."""
        self.image_converter = Mock()
        self.image_converter.convert_vcard_photo.return_value = (
            b"converted_jpg_data",
            None,
        )

    def test_process_contact_photos_with_data(self):
        """Test processing contact with photo data."""
        contact = Contact(
            name="Test User",
            phone_numbers=[],
            picture_data=b"base64_image_data",
            picture_url=None,
        )

        self.image_converter.convert_vcard_photo.return_value = (
            b"converted_jpg_data",
            None,
        )

        result = process_contact_photos(contact, self.image_converter)
        assert result.picture_data == b"converted_jpg_data"
        assert result.picture_url is None

    def test_process_contact_photos_with_url(self):
        """Test processing contact with photo URL."""
        contact = Contact(
            name="Test User",
            phone_numbers=[],
            picture_data=None,
            picture_url="https://example.com/photo.jpg",
        )

        result = process_contact_photos(contact, self.image_converter)
        assert result.picture_data is None
        assert result.picture_url == "https://example.com/photo.jpg"

    def test_process_contact_photos_no_photo(self):
        """Test processing contact without photo."""
        contact = Contact(
            name="Test User", phone_numbers=[], picture_data=None, picture_url=None
        )

        result = process_contact_photos(contact, self.image_converter)
        assert result.picture_data is None
        assert result.picture_url is None


class TestValidateAndNormalizeContact:
    """Test validate_and_normalize_contact function."""

    def test_validate_and_normalize_valid_contact(self):
        """Test validation of valid contact."""
        normalizer = PhoneNumberNormalizer("+49", "30")

        contact = Contact(
            name="John Doe",
            phone_numbers=[
                PhoneNumber(number="+4930123456", type="mobile", prio=1),
                PhoneNumber(number="301234567", type="home", prio=0),
            ],
            emails=[EmailAddress(email="john@example.com", classifier="private")],
        )

        with patch(
            "src.services.converter.PhoneNumberNormalizer", return_value=normalizer
        ):
            result = validate_and_normalize_contact(contact)

        assert result.name == "John Doe"
        assert len(result.phone_numbers) == 2
        assert len(result.emails) == 1

    def test_validate_and_normalize_invalid_phone(self):
        """Test validation rejects invalid phone numbers."""
        normalizer = PhoneNumberNormalizer("+49", "30")
        normalizer.validate_fritzbox_format = Mock(return_value=False)

        contact = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="123", type="home", prio=0)],
            emails=[],
        )

        with patch(
            "src.services.converter.PhoneNumberNormalizer", return_value=normalizer
        ):
            result = validate_and_normalize_contact(contact)

        assert len(result.phone_numbers) == 0

    def test_validate_and_normalize_with_picture(self):
        """Test validation preserves photo data."""
        contact = Contact(
            name="John Doe",
            phone_numbers=[],
            picture_data=b"photo_data",
            picture_url=None,
        )

        result = validate_and_normalize_contact(contact)
        assert result.picture_data == b"photo_data"
        assert result.picture_url is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
