"""Main package for CardDAV to FritzBox sync utility.

This package provides the core functionality for:
- Synchronizing contacts from multiple CardDAV sources
- Normalizing and formatting phone numbers for FritzBox
- Handling vCard images and conversions
- Uploading contacts to FritzBox devices
- Command-line interface for non-interactive execution

The main entry point is the CLI interface in main.py.
"""

from src.services.converter import (
    ImageConverter,
    PhoneNumberNormalizer,
    extract_phone_number_info,
    process_contact_photos,
    validate_and_normalize_contact,
)
from src.services.fritzbox_uploader import (
    ContactXML,
    FritzBoxUploader,
    PhonebookXML,
    XMLGenerator,
)
from src.utils.logger import setup_logger

__all__ = [
    "FritzBoxUploader",
    "XMLGenerator",
    "PhonebookXML",
    "ContactXML",
    "PhoneNumberNormalizer",
    "ImageConverter",
    "extract_phone_number_info",
    "process_contact_photos",
    "validate_and_normalize_contact",
    "setup_logger",
]
