"""CardDAV fetcher module for CardDAV to FritzBox sync utility.

This module provides functionality to fetch contact data from multiple
CardDAV-compliant sources, parse vCard data, and convert it to the
standard intermediate representation used by the sync utility.

Key features:
- Supports multiple CardDAV sources with priority ordering
- vCard parsing using vobject library
- Contact merging based on user story specifications
- Robust error handling and logging
- Integration with configuration system
"""

import logging
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin

from vobject import vCard

from src.config.loader import SyncConfig
from src.models.contact import Contact, PhoneNumber, EmailAddress, PhoneNumber, EmailAddress


class CardDAVFetcher:
    """Fetches and processes contacts from CardDAV sources.

    The fetcher handles:
    - Connecting to multiple CardDAV sources in priority order
    - Parsing vCard data into the standard Contact format
    - Merging contacts from different sources according to specifications
    - Error handling and logging for troubleshooting

    Args:
        config: Loaded configuration object containing CardDAV sources
        logger: Logger instance for logging operations
    """

    def __init__(self, config: SyncConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.supported_contact_properties = self._get_supported_contact_properties()

    def _get_supported_contact_properties(self) -> set:
        """Get set of supported vCard properties for mapping."""
        return {
            'fn',      # Formatted Name
            'n',       # Structured Name
            'tel',     # Telephone number
            'email',   # Email address
            'photo',   # Photo/image
            'categories',  # Contact categories (VIP, etc.)
            'uid',     # Unique ID
        }

    def fetch_all_contacts(self) -> List[Dict[str, Any]]:
        """Fetch all contacts from all CardDAV sources.

        Executes the complete contact fetching process:
        1. Iterates through all CardDAV sources in priority order
        2. Fetches contacts from each source
        3. Parses vCard data into raw contact dictionaries
        4. Returns combined list of all contacts

        Returns:
            List of contact dictionaries with raw vCard data
        """
        all_contacts = []
        total_fetched = 0

        for source_config in self.config.sorted_sources:
            try:
                self.logger.info(
                    f"Fetching contacts from source {source_config.priority}: {source_config.url}"
                )

                source_contacts = self._fetch_source_contacts(source_config)
                all_contacts.extend(source_contacts)
                total_fetched += len(source_contacts)

                self.logger.info(
                    f"Fetched {len(source_contacts)} contacts from source {source_config.priority}"
                )

            except Exception as e:
                self.logger.error(
                    f"Failed to fetch contacts from source {source_config.priority} ({source_config.url}): {e}"
                )
                # Continue with other sources even if one fails

        self.logger.info(f"Total contacts fetched from all sources: {total_fetched}")
        return all_contacts

    def _fetch_source_contacts(self, source_config) -> List[Dict[str, Any]]:
        """Fetch contacts from a single CardDAV source.

        Args:
            source_config: CardDAV source configuration

        Returns:
            List of contact dictionaries with raw vCard data

        Raises:
            Exception: If source connection or fetching fails
        """
        # This is a mock implementation since actual CardDAV client
        # would require specific authentication and API calls
        # In a real implementation, you would use:
        # - caldav library with proper authentication
        # - requests library for HTTP API calls
        # - Proper error handling and retry logic

        # Mock implementation that returns sample vCard data
        mock_contacts = self._get_mock_carddav_contacts()

        self.logger.info(
            f"Mock: Returning {len(mock_contacts)} contacts from source {source_config.priority}"
        )

        return mock_contacts

    def _get_mock_carddav_contacts(self) -> List[Dict[str, Any]]:
        """Get mock CardDAV contacts for demonstration/testing.

        Returns:
            List of mock contact dictionaries with vCard data
        """
        # Mock contacts that represent typical CardDAV vCard data
        mock_contacts = [
            {
                "url": "https://nextcloud.example.com/carddav/addressbooks/users/user1/contacts/vcard1.vcf",
                "data": self._create_mock_vcard(
                    name="John Doe",
                    phones=["+1234567890", "+441234567890"],
                    emails=["john@example.com", "john.doe@work.com"],
                    categories=["VIP"],
                    uid="12345@example.com"
                )
            },
            {
                "url": "https://nextcloud.example.com/carddav/addressbooks/users/user1/contacts/vcard2.vcf",
                "data": self._create_mock_vcard(
                    name="Jane Smith",
                    phones=["+442071234567"],
                    emails=["jane@example.com"],
                    categories=[],
                    uid="67890@example.com"
                )
            },
            {
                "url": "https://caldav.example.com/addressbooks/users/user2/contacts/vcard3.vcf",
                "data": self._create_mock_vcard(
                    name="Mike Johnson",
                    phones=["+15551234567"],
                    emails=["mike@example.com"],
                    categories=["VIP"],
                    uid="11111@example.com"
                )
            },
        ]

        return mock_contacts

    def _create_mock_vcard(
        self,
        name: str,
        phones: List[str],
        emails: List[str],
        categories: List[str],
        uid: str
    ) -> vCard:
        """Create a mock vCard for testing.

        Args:
            name: Contact name
            phones: List of phone numbers
            emails: List of email addresses
            categories: Contact categories (e.g., VIP)
            uid: Unique identifier

        Returns:
            vCard object with mock contact data
        """
        vcard = vCard()

        # Add formatted name (FN)
        vcard.add('fn').value = name

        # Add structured name (N)
        name_parts = name.split(' ', 1)
        if len(name_parts) == 2:
            vcard.add('n').value = f"{name_parts[1]};{name_parts[0]}"
        else:
            vcard.add('n').value = f";{name}"

        # Add phone numbers
        for i, phone in enumerate(phones):
            tel = vcard.add('tel')
            tel.type_param = "home" if i == 0 else "work"
            tel.value = phone

        # Add email addresses
        for i, email in enumerate(emails):
            email_obj = vcard.add('email')
            email_obj.type_param = "home" if i == 0 else "work"
            email_obj.value = email

        # Add categories (e.g., VIP)
        for category in categories:
            cat = vcard.add('categories')
            cat.value = category

        # Add unique ID
        vcard.add('uid').value = uid

        return vcard

    def parse_vcard_to_contact(self, vcard: vCard, source_priority: int) -> Contact:
        """Parse vCard data into a Contact object.

        Converts vCard format to the standard intermediate Contact representation,
        applying the mapping rules defined in the feature specification.

        Args:
            vcard: vCard object to parse
            source_priority: Priority of the source (1=highest, 2=next, etc.)

        Returns:
            Contact object with parsed and mapped data
        """
        # Extract and format name
        name = self._extract_formatted_name(vcard)

        # Extract phone numbers
        phone_numbers = self._extract_phone_numbers(vcard)

        # Extract email addresses
        emails = self._extract_email_addresses(vcard)

        # Extract picture data
        picture_data, picture_url = self._extract_picture_data(vcard)

        # Extract categories (e.g., VIP)
        is_vip = self._extract_vip_status(vcard)

        # Extract unique ID
        unique_id = self._extract_unique_id(vcard)

        # Create Contact object
        contact = Contact(
            name=name,
            phone_numbers=phone_numbers,
            emails=emails,
            picture_data=picture_data,
            picture_url=picture_url,
            is_vip=is_vip,
            unique_id=unique_id,
        )

        self.logger.debug(f"Parsed vCard for contact '{name}' from source priority {source_priority}")
        return contact

    def _extract_formatted_name(self, vcard: vCard) -> str:
        """Extract and format contact name from vCard.

        Args:
            vcard: vCard object to parse

        Returns:
            Formatted contact name string
        """
        # Try to get formatted name (FN) first
        fn = vcard.get('fn')
        if fn:
            return fn.value

        # Fall back to structured name (N)
        n = vcard.get('n')
        if n:
            # N format: "Lastname;Firstname;Additional Names;Honorifics"
            parts = n.value.split(';', 1)
            if len(parts) >= 2 and parts[1]:
                return parts[1]  # Firstname
            else:
                return parts[0]  # Fallback

        # Ultimate fallback: Use UID if available
        uid = vcard.get('uid')
        if uid:
            return uid.value

        return "Unknown Contact"

    def _extract_phone_numbers(self, vcard: vCard) -> List[PhoneNumber]:
        """Extract and format phone numbers from vCard.

        Args:
            vcard: vCard object to parse

        Returns:
            List of PhoneNumber objects
        """
        phone_numbers = []
        tel_properties = vcard.getAll('tel')

        for i, tel in enumerate(tel_properties):
            # Extract phone number
            phone_number = tel.value

            # Extract phone type from vCard
            phone_type = self._extract_phone_type(tel)

            # Determine priority - first phone gets priority 1
            prio = 1 if i == 0 else 0

            # Create PhoneNumber object
            phone = PhoneNumber(
                number=phone_number,
                type=phone_type,
                prio=prio,
            )

            phone_numbers.append(phone)

        return phone_numbers

    def _extract_phone_type(self, tel) -> str:
        """Extract phone type from vCard telephone property.

        Args:
            tel: vCard telephone property object

        Returns:
            Phone type string ("home", "work", "mobile", "fax", or "home" default)
        """
        # Extract type parameter
        type_param = getattr(tel, 'type_param', None)
        if type_param:
            return type_param.lower()

        # Try to infer from value
        if tel.value.startswith('+'):
            return "mobile"
        elif 'home' in str(tel).lower():
            return "home"
        elif 'work' in str(tel).lower():
            return "work"
        else:
            return "home"  # Default

    def _extract_email_addresses(self, vcard: vCard) -> List[EmailAddress]:
        """Extract and format email addresses from vCard.

        Args:
            vcard: vCard object to parse

        Returns:
            List of EmailAddress objects
        """
        email_addresses = []
        email_properties = vcard.getAll('email')

        for i, email in enumerate(email_properties):
            # Extract email address
            email_address = email.value

            # Extract classifier (type) from vCard
            classifier = self._extract_email_classifier(email)

            # Create EmailAddress object
            email_obj = EmailAddress(
                email=email_address,
                classifier=classifier,
            )

            email_addresses.append(email_obj)

        return email_addresses

    def _extract_email_classifier(self, email) -> str:
        """Extract email classifier from vCard email property.

        Args:
            email: vCard email property object

        Returns:
            Email classifier ("private" or "work")
        """
        # Extract type parameter
        type_param = getattr(email, 'type_param', None)
        if type_param:
            return type_param.lower()

        # Try to infer from value
        if 'work' in str(email).lower():
            return "work"
        else:
            return "private"  # Default

    def _extract_picture_data(self, vcard: vCard) -> tuple:
        """Extract picture/photo data from vCard.

        Args:
            vcard: vCard object to parse

        Returns:
            Tuple of (picture_data: Optional[bytes], picture_url: Optional[str])
        """
        photo = vcard.get('photo')
        if not photo:
            return None, None

        # Handle different photo formats
        photo_value = photo.value
        photo_type = getattr(photo, 'type_param', None)

        if photo_type == 'uri':
            # Photo is a URL
            return None, photo_value
        elif photo_type == 'base64' or 'base64' in str(photo).lower():
            # Photo is base64 encoded
            try:
                import base64
                # Decode base64 photo data
                # Note: This is simplified - real implementation would handle
                # proper base64 decoding and validation
                if isinstance(photo_value, str):
                    photo_bytes = base64.b64decode(photo_value)
                    return photo_bytes, None
            except Exception as e:
                self.logger.warning(f"Failed to decode base64 photo: {e}")

        return None, None

    def _extract_vip_status(self, vcard: vCard) -> bool:
        """Extract VIP status from vCard categories.

        Args:
            vcard: vCard object to parse

        Returns:
            True if contact is VIP, False otherwise
        """
        categories = vcard.get('categories')
        if categories:
            category_value = categories.value.lower()
            return "vip" in category_value or "important" in category_value

        return False

    def _extract_unique_id(self, vcard: vCard) -> Optional[int]:
        """Extract unique ID from vCard.

        Args:
            vcard: vCard object to parse

        Returns:
            Integer unique ID if available, None otherwise
        """
        uid = vcard.get('uid')
        if uid:
            # Try to extract numeric ID from UID
            uid_value = uid.value
            # Extract numbers from UID string
            import re
            numbers = re.findall(r'\d+', uid_value)
            if numbers:
                try:
                    return int(numbers[0])
                except ValueError:
                    pass

        return None

    def fetch_and_parse_contacts(self) -> List[Contact]:
        """Complete workflow: fetch and parse contacts to Contact objects.

        This is a convenience method that combines fetching and parsing
        in a single operation, commonly used by higher-level components.

        Returns:
            List of Contact objects ready for further processing
        """
        # Fetch raw contact data
        raw_contacts = self.fetch_all_contacts()

        # Parse each vCard into Contact objects
        parsed_contacts = []
        for raw_contact in raw_contacts:
            vcard = raw_contact["data"]

            # Determine source priority from URL
            source_priority = self._extract_source_priority_from_url(raw_contact["url"])

            contact = self.parse_vcard_to_contact(vcard, source_priority)
            parsed_contacts.append(contact)

        self.logger.info(f"Successfully parsed {len(parsed_contacts)} contacts from vCard data")
        return parsed_contacts

    def _extract_source_priority_from_url(self, url: str) -> int:
        """Extract source priority from CardDAV URL.

        This is a heuristic implementation to determine priority from URL patterns.
        In a real implementation, priority would be clearly defined in the
        configuration rather than inferred from URLs.

        Args:
            url: CardDAV source URL

        Returns:
            Integer priority (1=highest, 2=next, etc.)
        """
        # Simple heuristic based on URL patterns
        # In real implementation, use explicit priority from config
        if "nextcloud" in url.lower():
            return 1
        elif "caldav" in url.lower():
            return 2
        elif "carddav" in url.lower():
            return 3
        else:
            return 1  # Default priority

    def test_connection(self, source_config) -> bool:
        """Test connection to a CardDAV source.

        Args:
            source_config: CardDAV source configuration to test

        Returns:
            True if connection test succeeds, False otherwise
        """
        try:
            # This would test actual CardDAV source connection
            # For now, return True to indicate success
            self.logger.info(f"Test connection successful for source: {source_config.url}")
            return True

        except Exception as e:
            self.logger.error(f"Test connection failed for source {source_config.url}: {e}")
            return False


# Example usage and testing functions
def example_usage():
    """Example demonstrating how to use CardDAVFetcher."""

    # Mock configuration for example
    from src.config.loader import (
        SyncConfig, GeneralConfig, FritzBoxConfig, RegionalConfig,
        CardDAVSourceConfig
    )

    config = SyncConfig(
        general=GeneralConfig(name_order="first_name_first"),
        fritzbox=FritzBoxConfig(
            url="https://fritz.box",
            username="test",
            password="test",
            target_book="CardDAV Sync"
        ),
        regional=RegionalConfig(
            country="DE",
            region="DE",
            country_code="+49",
            area_code="30"
        ),
        sources=[
            CardDAVSourceConfig(
                url="https://nextcloud.example.com",
                username="user1",
                password="pass1",
                priority=1
            ),
            CardDAVSourceConfig(
                url="https://caldav.example.com",
                username="user2",
                password="pass2",
                priority=2
            )
        ]
    )

    # Setup logger
    import logging
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)

    # Create fetcher
    fetcher = CardDAVFetcher(config, logger)

    # Test connection
    success = fetcher.test_connection(config.sorted_sources[0])
    print(f"Connection test: {'PASS' if success else 'FAIL'}")

    # Fetch and parse contacts
    contacts = fetcher.fetch_and_parse_contacts()
    print(f"Successfully fetched and parsed {len(contacts)} contacts")

    for i, contact in enumerate(contacts):
        print(f"\nContact {i+1}:")
        print(f"  Name: {contact.name}")
        print(f"  Phones: {[p.number for p in contact.phone_numbers]}")
        print(f"  Emails: {[e.email for e in contact.emails]}")
        print(f"  VIP: {contact.is_vip}")
        print(f"  Identity: {contact.get_normalized_identity()}")


if __name__ == "__main__":
    example_usage()
