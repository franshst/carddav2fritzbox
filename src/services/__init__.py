"""Services module for CardDAV to FritzBox sync utility.

This module provides core services for the sync utility:
- CardDAV fetcher for retrieving contacts from CardDAV sources
- Normalization and conversion module for phone numbers and images
- FritzBox uploader for managing contacts on FritzBox devices
- CLI interface for user interaction

The services are organized by functionality:
1. External data sources (CardDAV fetcher)
2. Data transformation (converter module)
3. External system integration (FritzBox uploader)
"""

from src.services.carddav_fetcher import CardDAVFetcher
from src.services.converter import (
    ImageConverter,
    PhoneNumberNormalizer,
    process_contact_photos,
    validate_and_normalize_contact,
)
from src.services.fritzbox_uploader import (
    ContactXML,
    FritzBoxUploader,
    PhonebookXML,
)

__all__ = [
    "CardDAVFetcher",
    "FritzBoxUploader",
    "PhonebookXML",
    "ContactXML",
    "PhoneNumberNormalizer",
    "ImageConverter",
    "process_contact_photos",
    "validate_and_normalize_contact",
]
