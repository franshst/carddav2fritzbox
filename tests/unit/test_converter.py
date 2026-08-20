"""Unit tests for phone number normalization and image conversion utilities.

Tests the converter module functionality:
- PhoneNumberNormalizer for phone number processing
- ImageConverter for vCard image handling
- Helper functions for contact processing
"""

import base64
from unittest.mock import Mock, patch

import pytest

from src.models.contact import Contact, EmailAddress, PhoneNumber
from src.services.converter import (
    ImageConverter,
    PhoneNumberNormalizer,
    process_contact_photos,
    validate_and_normalize_contact,
)


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
        """Test shortening for FritzBox (FR-006): local number drops +/CC and its own
        area code, leaving the bare subscriber number."""
        normalizer = PhoneNumberNormalizer("+49", "30")
        result = normalizer.format_for_fritzbox("+4930123467")
        assert result == "123467"

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

    # --- FR-014 sanitization ---

    def test_sanitize_strips_non_numeric_preserves_leading_plus(self):
        """Test that sanitization strips non-numeric chars but keeps '+'
        (FR-014)."""
        normalizer = PhoneNumberNormalizer("+49", "30", "00")
        assert normalizer.sanitize("+49 (30) 123-456.") == "+4930123456"

    def test_sanitize_empty_string(self):
        """Test that sanitization of an empty string returns empty."""
        normalizer = PhoneNumberNormalizer("+49", "30", "00")
        assert normalizer.sanitize("") == ""

    # --- FR-005 canonical normalization ---

    def test_normalize_plus_passthrough(self):
        """Test that a number starting with '+' is already canonical (FR-005)."""
        normalizer = PhoneNumberNormalizer("+49", "30", "00")
        assert normalizer.normalize("+4930123456") == "+4930123456"

    def test_normalize_international_access_code_replaced(self):
        """Test that the configured access code is replaced with '+' (FR-005)."""
        normalizer = PhoneNumberNormalizer("+49", "30", "00")
        assert normalizer.normalize("004930123456") == "+4930123456"

    def test_normalize_custom_international_access_code(self):
        """Test with a US-style international access code (011)."""
        normalizer = PhoneNumberNormalizer("+1", "650", "011")
        assert normalizer.normalize("011144125552671") == "+144125552671"

    def test_normalize_leading_zero_replaced_with_country_code(self):
        """Test that a leading '0' becomes '+' + country code (FR-005)."""
        normalizer = PhoneNumberNormalizer("+49", "30", "00")
        assert normalizer.normalize("030123456") == "+4930123456"

    def test_normalize_prepends_country_and_area_code(self):
        """Test prepending '+' + country code + area code (FR-005)."""
        normalizer = PhoneNumberNormalizer("+49", "30", "00")
        assert normalizer.normalize("1234567") == "+49301234567"

    def test_normalize_area_code_without_leading_zero(self):
        """Test that a leading zero in the configured area code is dropped."""
        normalizer = PhoneNumberNormalizer("+49", "030", "00")
        assert normalizer.normalize("1234567") == "+49301234567"

    def test_normalize_sanitizes_before_canonicalizing(self):
        """Test that sanitization happens before canonicalization (FR-014/005)."""
        normalizer = PhoneNumberNormalizer("+49", "30", "00")
        assert normalizer.normalize("+49 (30) 123-456") == "+4930123456"

    def test_normalize_no_digits_returns_empty(self):
        """Test that a number with no digits cannot be normalized (FR-019)."""
        normalizer = PhoneNumberNormalizer("+49", "30", "00")
        assert normalizer.normalize("(abc)") == ""

    def test_normalize_e164_without_plus(self):
        """E.164 without '+' (e.g. Nextcloud '31703141414') stays intact."""
        normalizer = PhoneNumberNormalizer("+31", "20", "00")
        assert normalizer.normalize("31703141414") == "+31703141414"
        assert normalizer.normalize("0882692888") == "+31882692888"

    # --- FR-006 FritzBox shortening ---

    def test_shorten_local_same_area(self):
        """Numbers in the book's own area code become the bare subscriber number
        (the trunk 0 and area code are not dialed within the same area)."""
        normalizer = PhoneNumberNormalizer("+49", "30", "00")
        assert normalizer.shorten("+4930123456") == "123456"

    def test_shorten_local_different_area(self):
        """Test keeping the area code when it differs from the configured one."""
        normalizer = PhoneNumberNormalizer("+49", "30", "00")
        assert normalizer.shorten("+4940222111") == "040222111"

    def test_shorten_mobile_number(self):
        """Test that a mobile number only loses '+' and country code."""
        normalizer = PhoneNumberNormalizer("+49", "30", "00")
        assert normalizer.shorten("+491512345678") == "01512345678"

    def test_shorten_nl_bare_subscriber_number(self):
        """NL regression: '020-448-6970' canonicalizes to '+31204486970' and
        shortens to the bare subscriber number '4486970' (the trunk 0 and area
        code are not dialed within the same area)."""
        normalizer = PhoneNumberNormalizer("+31", "20", "00")
        assert normalizer.normalize("020-448-6970") == "+31204486970"
        assert normalizer.shorten("+31204486970") == "4486970"

    def test_shorten_foreign_number_kept_canonical(self):
        """Test that a foreign number stays in canonical form (FR-006)."""
        normalizer = PhoneNumberNormalizer("+49", "30", "00")
        assert normalizer.shorten("+442079460958") == "+442079460958"

    def test_shorten_number_without_plus_passthrough(self):
        """Test that a non-canonical input passes through unchanged."""
        normalizer = PhoneNumberNormalizer("+49", "30", "00")
        assert normalizer.shorten("30123456") == "30123456"

    def test_format_for_fritzbox_uses_shorten(self):
        """Test that format_for_fritzbox is the export-time shortening step."""
        normalizer = PhoneNumberNormalizer("+49", "30", "00")
        assert normalizer.format_for_fritzbox("+4930123456") == "123456"


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

    # --- FR-019 skip unnormalizable numbers with warning ---

    def test_validate_skips_unnormalizable_with_warning(self, capsys):
        """Test that unnormalizable numbers are skipped with a stderr warning
        while valid ones are kept (FR-019)."""
        normalizer = PhoneNumberNormalizer("+49", "30", "00")
        contact = Contact(
            name="John Doe",
            phone_numbers=[
                PhoneNumber(number="(abc)", type="home", prio=0),
                PhoneNumber(number="030123456", type="mobile", prio=1),
            ],
            emails=[EmailAddress(email="john@example.com", classifier="private")],
        )

        result = validate_and_normalize_contact(contact, normalizer)

        assert result.name == "John Doe"
        assert len(result.phone_numbers) == 1
        assert result.phone_numbers[0].number == "+4930123456"
        assert len(result.emails) == 1

        captured = capsys.readouterr()
        assert "Skipping unnormalizable phone number" in captured.err
        assert "(abc)" in captured.err

    def test_validate_all_unnormalizable_keeps_contact(self, capsys):
        """Test that a contact survives when all its numbers are skipped."""
        normalizer = PhoneNumberNormalizer("+49", "30", "00")
        contact = Contact(
            name="Jane Doe",
            phone_numbers=[PhoneNumber(number="no-digits", type="home", prio=0)],
            emails=[],
        )

        result = validate_and_normalize_contact(contact, normalizer)

        assert result.name == "Jane Doe"
        assert len(result.phone_numbers) == 0

        captured = capsys.readouterr()
        assert "Skipping" in captured.err

    def test_validate_stores_canonical_not_shortened(self):
        """Test that the normalize stage stores canonical form (FR-018)."""
        normalizer = PhoneNumberNormalizer("+49", "30", "00")
        contact = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="030123456", type="mobile", prio=1)],
            emails=[],
        )

        result = validate_and_normalize_contact(contact, normalizer)

        assert result.phone_numbers[0].number == "+4930123456"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
