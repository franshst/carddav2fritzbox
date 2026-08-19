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
from typing import Optional, Tuple, Union
from io import BytesIO
from PIL import Image
from src.models.contact import PhoneNumber, Contact


class PhoneNumberNormalizer:
    """Handles phone number normalization and formatting for FritzBox compatibility.

    The normalizer performs the following operations:
    1. Strips all non-numeric characters (preserving leading '+' for country codes)
    2. Applies regional formatting based on FritzBox configuration
    3. Validates phone number format for FritzBox constraints
    """

    def __init__(self, country_code: str = "+49", region_code: str = "30"):
        """Initialize the phone number normalizer.

        Args:
            country_code: Country code for phone number formatting (e.g., "+49")
            region_code: Region code for phone number formatting (e.g., "30")
        """
        self.country_code = country_code
        self.region_code = region_code

    def normalize(self, phone_number: str) -> str:
        """Normalize a phone number by stripping all non-numeric characters.

        Args:
            phone_number: Raw phone number string (e.g., "+1 (415) 555-2671")

        Returns:
            Normalized phone number with only digits and leading '+'
        """
        # Strip all non-numeric characters except leading '+'
        normalized = re.sub(r'[^0-9+]', '', phone_number)

        # Add country code if missing and number appears to be local
        # Simple heuristic: if starts with digit (not '+'), add country code
        if normalized and not normalized.startswith('+') and len(normalized) >= 7:
            normalized = f"{self.country_code}{normalized}"

        return normalized

    def format_for_fritzbox(self, phone_number: str) -> str:
        """Format phone number for FritzBox XML export.

        Args:
            phone_number: Normalized phone number

        Returns:
            Phone number formatted for FritzBox
        """
        # Ensure primary number has proper prefix if missing
        if phone_number and not phone_number.startswith('+'):
            # Add country code for international numbers based on regional config
            if self.region_code != "30":  # Non-German region
                phone_number = f"{self.country_code}{phone_number}"

        return phone_number

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
        if phone_number.startswith('+'):
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
        return phone_number.replace('+', '').isdigit()


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

    def convert_vcard_photo(self, photo_data: Union[str, bytes], 
                           photo_type: Optional[str] = None) -> Tuple[Optional[bytes], Optional[str]]:
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
                if photo_type == 'uri' or photo_data.startswith('http'):
                    # External URI - return as-is (can't download automatically)
                    return None, photo_data

                # Try to decode as Base64 (vCard standard)
                try:
                    image_bytes = base64.b64decode(photo_data)
                    is_base64 = True
                except base64.binascii.Error:
                    # If Base64 decode fails, treat as raw bytes
                    image_bytes = photo_data.encode('utf-8')
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

    def _convert_image_bytes_to_jpg(self, image_bytes: bytes, is_base64: bool) -> Tuple[Optional[bytes], Optional[str]]:
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


def extract_phone_number_info(phone: str, phone_type: str = "home", prio: int = 0) -> PhoneNumber:
    """Create a PhoneNumber object with normalization applied.

    Args:
        phone: Raw phone number string
        phone_type: Type of phone ("home", "mobile", "work", "fax")
        prio: Priority (1 for primary, 0 for secondary)

    Returns:
        PhoneNumber object with normalized number
    """
    normalizer = PhoneNumberNormalizer()
    normalized_number = normalizer.normalize(phone)
    formatted_number = normalizer.format_for_fritzbox(normalized_number)

    return PhoneNumber(
        number=formatted_number,
        type=phone_type,
        prio=prio,
        quickdial="",
        vanity=""
    )


def process_contact_photos(contact: Contact, image_converter: ImageConverter) -> Contact:
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
            contact.picture_data, photo_type='base64'
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
        if not (contact.picture_url.startswith('http://') or contact.picture_url.startswith('https://')):
            # Try to decode as Base64 if it's in data URL format
            if ',' in contact.picture_url:
                header, data = contact.picture_url.split(',', 1)
                if 'base64' in header:
                    try:
                        jpg_data, _ = image_converter.convert_vcard_photo(data, photo_type='base64')
                        if jpg_data:
                            contact.picture_data = jpg_data
                        contact.picture_url = None
                    except:
                        pass

    return contact


def validate_and_normalize_contact(contact: Contact, normalizer: Optional[PhoneNumberNormalizer] = None) -> Contact:
    """Validate contact data and apply necessary normalizations.

    Args:
        contact: Contact object to validate and normalize
        normalizer: Optional PhoneNumberNormalizer object for custom regional configuration

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
        unique_id=contact.unique_id
    )

    # Process each phone number
    for phone_number in contact.phone_numbers:
        normalized_str = normalizer.normalize(phone_number.number)
        formatted_str = normalizer.format_for_fritzbox(normalized_str)
        if normalizer.validate_fritzbox_format(formatted_str):
            normalized_phone = PhoneNumber(
                number=formatted_str,
                type=phone_number.type,
                prio=phone_number.prio,
                quickdial=phone_number.quickdial,
                vanity=phone_number.vanity
            )
            validated_contact.phone_numbers.append(normalized_phone)
        else:
            # Log warning for invalid phone numbers
            print(f"Warning: Invalid phone number format: {phone_number.number}")

    # Add emails (no normalization needed for FritzBox)
    validated_contact.emails = contact.emails.copy()

    return validated_contact


if __name__ == "__main__":
    # Example usage
    print("Phone Number Normalizer Example:")
    normalizer = PhoneNumberNormalizer("+49", "30")

    test_numbers = [
        "+1 (415) 555-2671",
        "44 20 7946 0958",
        "030-1234567",
        "+49 30 123456"
    ]

    for number in test_numbers:
        normalized = normalizer.normalize(number)
        formatted = normalizer.format_for_fritzbox(normalized)
        print(f"Original: {number}")
        print(f"Normalized: {normalized}")
        print(f"Formatted: {formatted}")
        print(f"Valid: {normalizer.validate_fritzbox_format(formatted)}")
        print()

    print("Image Converter Example:")
    converter = ImageConverter()
