"""Normalization and conversion module for CardDAV to FritzBox sync utility.

This module provides functionality to normalize phone numbers and convert
vCard images to FritzBox-compatible formats.

Key features:
- Phone number normalization and formatting
- vCard image processing (Base64 to JPG conversion)
- Integration with Contact models and FritzBox requirements
"""

import base64
import re
import sys
from io import BytesIO
from typing import Optional, Tuple, Union

from PIL import Image

from src.models.contact import Contact, PhoneNumber, canonicalize_phone


class PhoneNumberNormalizer:
    """Handles phone number normalization and FritzBox shortening.

    Implements the three-stage model (spec.md data-model.md):
    - *Normalize* (FR-005): sanitize (FR-014) then convert to the canonical
      form (``+`` country code + number) via :func:`canonicalize_phone`.
    - *Shorten* (FR-006): at FritzBox export, local numbers (book's configured
      country code) lose the ``+`` and country code. In the book's own area code
      they are stored as the bare subscriber number (trunk ``0`` and area code
      are not dialed within the same area); other local numbers gain a leading
      ``0`` and keep their area code. Foreign numbers stay in canonical form.
    """

    def __init__(
        self,
        country_code: str = "",
        area_code: str = "",
        international_access_code: str = "",
    ):
        """Initialize the phone number normalizer.

        Args:
            country_code: Country code for normalization (e.g. "+49").
            area_code: Area code for normalization (e.g. "30").
            international_access_code: International access code (e.g. "00").
        """
        self.country_code = country_code
        self.area_code = area_code
        self.international_access_code = international_access_code

    def sanitize(self, phone_number: str) -> str:
        """Sanitize a phone number (FR-014): strip all non-numeric characters
        while preserving a leading '+' for country/international detection.
        """
        return re.sub(r"[^0-9+]", "", phone_number or "")

    def normalize(self, phone_number: str) -> str:
        """Normalize a phone number to the canonical form (FR-005).

        Returns an empty string when the number cannot be normalized (no digits
        remain after sanitization) - see FR-019.
        """
        digits = self.sanitize(phone_number)
        if not digits:
            return ""
        return canonicalize_phone(
            digits,
            self.country_code,
            self.area_code,
            self.international_access_code,
        )

    def shorten(self, phone_number: str) -> str:
        """Shorten a canonical phone number for the FritzBox book (FR-006).

        Foreign-country numbers are kept in canonical form. Local numbers lose
        the ``+`` and country code. Numbers in the book's own area code are
        stored as the bare subscriber number (the trunk ``0`` and the area code
        are not dialed within the same area, e.g. in the Netherlands); other
        local numbers gain a leading ``0`` and keep their area code.
        """
        digits = self.sanitize(phone_number)
        if not digits.startswith("+"):
            return digits

        country_digits = re.sub(r"[^0-9]", "", self.country_code)
        if not country_digits or not digits.startswith("+" + country_digits):
            return digits

        national = digits[len(country_digits) + 1 :]
        area_digits = re.sub(r"[^0-9]", "", self.area_code).lstrip("0")
        if area_digits and national.startswith(area_digits):
            return national[len(area_digits) :]
        return "0" + national

    def format_for_fritzbox(self, phone_number: str) -> str:
        """Format a phone number for FritzBox XML export (FR-006).

        This is the export-time shortening step of the three-stage model.
        """
        return self.shorten(phone_number)

    def validate_fritzbox_format(self, phone_number: str) -> bool:
        """Validate phone number meets FritzBox requirements.

        Args:
            phone_number: Phone number to validate

        Returns:
            True if phone number is valid for FritzBox, False otherwise
        """
        if not phone_number:
            return False

        # FritzBox supports up to 9 phone numbers per contact (id="0" to "8")
        # Validate basic format
        if phone_number.startswith("+"):
            # International format: country code + national number
            # Must be at least 8 digits after country code
            digits = phone_number[1:]  # Remove '+'
            if len(digits) < 8 or len(digits) > 20:
                return False
        else:
            # Local format: must be 7-12 digits
            if len(phone_number) < 7 or len(phone_number) > 12:
                return False

        # Allow digits only (already normalized)
        return phone_number.replace("+", "").isdigit()


class ImageConverter:
    """Handles vCard image processing and conversion to FritzBox-compatible format.

    The converter supports:
    1. Processing Base64-encoded vCard PHOTO data
    2. Converting images to JPEG format (required by FritzBox)
    3. Resizing images to 300x300 pixels (maximum allowed size)
    4. Cropping to square aspect ratio for optimal display
    5. Graceful handling of corrupted or missing images
    """

    MAX_DIMENSION = 300
    SQUARE_ASPECT_RATIO = 1.0

    def __init__(self, logger=None):
        """Initialize the image converter.

        Args:
            logger: Optional logger for error reporting
        """
        self.logger = logger

    def convert_vcard_photo(
        self, photo_data: Union[str, bytes], photo_type: Optional[str] = None
    ) -> Tuple[Optional[bytes], Optional[str]]:
        """Convert vCard PHOTO data to FritzBox-compatible JPG format.

        Args:
            photo_data: Photo data as Base64 string or raw bytes
            photo_type: Optional photo type from vCard ("uri", "base64", etc.)

        Returns:
            Tuple of (converted_image_bytes, image_url)
            Returns (None, None) if conversion fails
        """
        try:
            # Handle different input formats
            if isinstance(photo_data, str):
                # Determine if it's Base64 encoded or raw binary
                if photo_type == "uri" or photo_data.startswith("http"):
                    # External URI - return as-is (can't download automatically)
                    return None, photo_data

                # Try to decode as Base64 (vCard standard)
                try:
                    image_bytes = base64.b64decode(photo_data)
                    is_base64 = True
                except base64.binascii.Error:
                    # If Base64 decode fails, treat as raw bytes
                    image_bytes = photo_data.encode("utf-8")
                    is_base64 = False
            else:
                # Raw bytes
                image_bytes = photo_data
                is_base64 = False

            # Convert to JPG using PIL
            return self._convert_image_bytes_to_jpg(image_bytes, is_base64)

        except Exception as e:
            self._log_warning(f"Failed to convert vCard photo: {e}")
            return None, None

    def _convert_image_bytes_to_jpg(
        self, image_bytes: bytes, is_base64: bool
    ) -> Tuple[Optional[bytes], Optional[str]]:
        """Convert image bytes to FritzBox-compatible JPG format.

        Args:
            image_bytes: Raw image bytes
            is_base64: Whether the bytes were originally Base64 encoded

        Returns:
            Tuple of (converted_jpg_bytes, None) or (None, None) on failure
        """
        try:
            # Open image with Pillow
            image = Image.open(BytesIO(image_bytes))

            # Convert to RGB (strips alpha transparent channels from PNG/GIF)
            if image.mode in ("RGBA", "P", "LA"):
                image = image.convert("RGB")

            # Center-crop to 1:1 square aspect ratio
            image = self._crop_to_square(image)

            # Resize to maximum 300x300 while maintaining aspect ratio
            image = self._resize_to_max_dimension(image)

            # Save as baseline JPEG
            output = BytesIO()
            image.save(output, format="JPEG", quality=85, progressive=False)
            jpg_bytes = output.getvalue()

            return jpg_bytes, None

        except Exception as e:
            self._log_warning(f"Failed to process image: {e}")
            return None, None

    def _crop_to_square(self, image: Image.Image) -> Image.Image:
        """Crop image to square aspect ratio (1:1).

        Args:
            image: PIL Image object

        Returns:
            Cropped square image
        """
        width, height = image.size
        min_dim = min(width, height)

        # Calculate center crop coordinates
        left = (width - min_dim) / 2
        top = (height - min_dim) / 2
        right = (width + min_dim) / 2
        bottom = (height + min_dim) / 2

        return image.crop((left, top, right, bottom))

    def _resize_to_max_dimension(self, image: Image.Image) -> Image.Image:
        """Resize image to fit within maximum dimensions while maintaining aspect ratio.

        Args:
            image: PIL Image object

        Returns:
            Resized image
        """
        width, height = image.size

        if width > self.MAX_DIMENSION or height > self.MAX_DIMENSION:
            if width > height:
                new_height = int(height * (self.MAX_DIMENSION / width))
                new_width = self.MAX_DIMENSION
            else:
                new_width = int(width * (self.MAX_DIMENSION / height))
                new_height = self.MAX_DIMENSION

            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        return image

    def _log_warning(self, message: str) -> None:
        """Log warning message if logger is available.

        Args:
            message: Warning message to log
        """
        if self.logger:
            self.logger.warning(message)
        else:
            print(f"Warning: {message}")


def process_contact_photos(
    contact: Contact, image_converter: ImageConverter
) -> Contact:
    """Process and convert contact photos to FritzBox-compatible format.

    Args:
        contact: Contact object with potential photo data
        image_converter: ImageConverter instance for photo processing

    Returns:
        Contact object with processed photos (or None if processing failed)
    """
    if contact.picture_data:
        # Convert Base64 photo data to FritzBox-compatible JPG
        jpg_data, _ = image_converter.convert_vcard_photo(
            contact.picture_data, photo_type="base64"
        )
        if jpg_data:
            contact.picture_data = jpg_data
        else:
            contact.picture_data = None
            contact.picture_url = None

    elif contact.picture_url:
        # For external URLs, attempt to convert if possible
        # Note: In production, this would require downloading the image
        # For now, keep as URL if it's a valid format
        if not (
            contact.picture_url.startswith("http://")
            or contact.picture_url.startswith("https://")
        ):
            # Try to decode as Base64 if it's in data URL format
            if "," in contact.picture_url:
                header, data = contact.picture_url.split(",", 1)
                if "base64" in header:
                    try:
                        jpg_data, _ = image_converter.convert_vcard_photo(
                            data, photo_type="base64"
                        )
                        if jpg_data:
                            contact.picture_data = jpg_data
                        contact.picture_url = None
                    except Exception:
                        pass

    return contact


def validate_and_normalize_contact(
    contact: Contact, normalizer: Optional[PhoneNumberNormalizer] = None
) -> Contact:
    """Validate contact data and normalize phone numbers to the canonical form.

    Implements the *Normalize* stage of the three-stage model: each phone number
    is sanitized (FR-014) and converted to the canonical form (FR-005). Numbers
    that cannot be normalized are skipped with a warning to stderr (FR-019).
    Shortening for FritzBox happens later, at export time (FR-006).

    Args:
        contact: Contact object to validate and normalize
        normalizer: Optional PhoneNumberNormalizer object for custom regional
            configuration

    Returns:
        Validated and normalized Contact object
    """
    if normalizer is None:
        normalizer = PhoneNumberNormalizer()

    # Create a copy to avoid modifying the original
    validated_contact = Contact(
        name=contact.name,
        phone_numbers=[],
        emails=[],
        picture_data=contact.picture_data,
        picture_url=contact.picture_url,
        is_vip=contact.is_vip,
        unique_id=contact.unique_id,
    )

    # Process each phone number
    for phone_number in contact.phone_numbers:
        normalized_str = normalizer.normalize(phone_number.number)
        if not normalized_str:
            print(
                f"Warning: Skipping unnormalizable phone number: "
                f"{phone_number.number!r}",
                file=sys.stderr,
            )
            continue
        if not normalizer.validate_fritzbox_format(normalized_str):
            print(
                f"Warning: Invalid phone number for FritzBox: {normalized_str}",
                file=sys.stderr,
            )
            continue
        normalized_phone = PhoneNumber(
            number=normalized_str,
            type=phone_number.type,
            prio=phone_number.prio,
            quickdial=phone_number.quickdial,
            vanity=phone_number.vanity,
        )
        validated_contact.phone_numbers.append(normalized_phone)

    # Add emails (no normalization needed for FritzBox)
    validated_contact.emails = contact.emails.copy()

    return validated_contact
