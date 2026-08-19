"""Services module for CardDAV to FritzBox sync utility.

This module provides core services for the sync utility:
- CardDAV fetcher for retrieving contacts from CardDAV sources
- Normalization and conversion module for phone numbers and images
- FritzBox uploader for managing contacts on FritzBox devices
- CLI interface for user interaction
"""

from src.services.carddav_fetcher import CardDAVFetcher
from src.services.converter import (
    PhoneNumberNormalizer,
    ImageConverter,
    extract_phone_number_info,
    process_contact_photos,
    validate_and_normalize_contact,
)

__all__ = [
    'CardDAVFetcher',
    'PhoneNumberNormalizer',
    'ImageConverter',
    'extract_phone_number_info',
    'process_contact_photos',
    'validate_and_normalize_contact',
]

"""Services submodule for CardDAV to FritzBox sync utility.

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
from src.services.fritzbox_uploader import (
    FritzBoxUploader,
    XMLGenerator,
    PhonebookXML,
    ContactXML,
)
from src.services.converter import (
    PhoneNumberNormalizer,
    ImageConverter,
    extract_phone_number_info,
    process_contact_photos,
    validate_and_normalize_contact,
)

__all__ = [
    'CardDAVFetcher',
    'FritzBoxUploader',
    'XMLGenerator',
    'PhonebookXML',
    'ContactXML',
    'PhoneNumberNormalizer',
    'ImageConverter',
    'extract_phone_number_info',
    'process_contact_photos',
    'validate_and_normalize_contact',
]
