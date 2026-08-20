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
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
import vobject
from vobject import vCard

from src.config.loader import SyncConfig
from src.models.contact import Contact, EmailAddress, PhoneNumber

_DAV_NS = "DAV:"
_CARDDAV_NS = "urn:ietf:params:xml:ns:carddav"
_TIMEOUT = 30


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
        self.timeout = _TIMEOUT
        self.supported_contact_properties = self._get_supported_contact_properties()

    def _get_supported_contact_properties(self) -> set:
        """Get set of supported vCard properties for mapping."""
        return {
            "fn",  # Formatted Name
            "n",  # Structured Name
            "tel",  # Telephone number
            "email",  # Email address
            "photo",  # Photo/image
            "categories",  # Contact categories (VIP, etc.)
            "uid",  # Unique ID
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
                    f"Fetching source {source_config.priority} ({source_config.url})"
                )

                source_contacts = self._fetch_source_contacts(source_config)
                all_contacts.extend(source_contacts)
                total_fetched += len(source_contacts)

                self.logger.info(
                    f"Fetched {len(source_contacts)} contacts "
                    f"(source {source_config.priority})"
                )

            except Exception as e:
                self.logger.error(
                    f"Source {source_config.priority} ({source_config.url}) failed: {e}"
                )
                # Continue with other sources even if one fails

        self.logger.info(f"Total contacts fetched from all sources: {total_fetched}")
        return all_contacts

    def _fetch_source_contacts(self, source_config) -> List[Dict[str, Any]]:
        """Fetch contacts from a single CardDAV source over RFC 6352.

        Flow (see contracts/carddav-api.md):
        1. Resolve the address-book home set via ``.well-known/carddav``
           (RFC 6764), falling back to a PROPFIND on the configured URL.
        2. PROPFIND the home set and collect hrefs whose ``resourcetype``
           contains a CardDAV ``addressbook`` resource.
        3. REPORT each address book with an ``addressbook-query`` asking for
           ``address-data`` and parse the returned vCards with ``vobject``.

        Args:
            source_config: CardDAV source configuration

        Returns:
            List of ``{"url", "data", "source_priority"}`` dicts with raw
            vCard data.

        Raises:
            ConnectionError: If the source is unreachable or a DAV request fails.
        """
        session = self._session_for(source_config)

        try:
            addressbooks = self._discover_addressbooks(session, source_config)
        except requests.RequestException as e:
            raise ConnectionError(
                f"CardDAV request failed for source {source_config.priority} "
                f"({source_config.url}): {e}"
            ) from e

        if not addressbooks:
            self.logger.warning(
                f"No CardDAV address books found at source {source_config.priority} "
                f"({source_config.url})"
            )
            return []

        raw_contacts = []
        for addressbook_url in addressbooks:
            self.logger.debug(f"Fetching vCards from address book {addressbook_url}")
            try:
                raw_contacts.extend(self._report_addressbook(session, addressbook_url))
            except requests.RequestException as e:
                raise ConnectionError(
                    f"Failed to fetch address book {addressbook_url}: {e}"
                ) from e

        for raw_contact in raw_contacts:
            raw_contact["source_priority"] = source_config.priority

        self.logger.info(
            f"Fetched {len(raw_contacts)} contacts from source {source_config.priority}"
        )
        return raw_contacts

    def _session_for(self, source_config) -> requests.Session:
        """Create a requests session authenticated for a CardDAV source."""
        session = requests.Session()
        session.auth = (source_config.username, source_config.password)
        session.headers.update({"User-Agent": "carddav2fritzbox/1.0"})
        return session

    def _discover_addressbooks(
        self, session: requests.Session, source_config
    ) -> List[str]:
        """Resolve the address-book home set and list its address books.

        Per RFC 6764 the well-known URI redirects to the home set; when that
        fails (e.g. server without well-known support) fall back to a PROPFIND
        on the configured source URL. When the home set responds but exposes no
        ``addressbook`` resources at Depth 1 (e.g. Nextcloud redirects to the
        generic ``/remote.php/dav`` root), the configured URL is probed too,
        since it may itself point directly at an address book.
        """
        base = source_config.url
        well_known = urljoin(base, "/.well-known/carddav")
        home_set = None

        try:
            response = session.get(
                well_known, timeout=self.timeout, allow_redirects=True
            )
            response.raise_for_status()
            # Only use the final URL if a redirect actually occurred.
            home_set = response.url if response.history else base
        except requests.RequestException as e:
            self.logger.warning(
                f".well-known/carddav lookup failed for {base}: {e}; "
                f"falling back to PROPFIND on the configured URL"
            )

        candidates = [home_set] if home_set else []
        if base not in candidates:
            candidates.append(base)

        addressbooks = []
        for target in candidates:
            try:
                addressbooks.extend(self._propfind_addressbooks(session, target))
            except requests.RequestException as e:
                self.logger.warning(
                    f"PROPFIND failed for {target}: {e}; "
                    f"trying next discovery candidate"
                )
            if addressbooks:
                break

        # Deduplicate while preserving discovery order (FR-009).
        seen = set()
        unique = []
        for addressbook in addressbooks:
            if addressbook not in seen:
                seen.add(addressbook)
                unique.append(addressbook)
        return unique

    def _propfind_addressbooks(self, session: requests.Session, url: str) -> List[str]:
        """PROPFIND a URL and collect hrefs that are CardDAV address books."""
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<d:propfind xmlns:d="{_DAV_NS}">'
            "<d:prop><d:resourcetype/><d:displayname/></d:prop>"
            "</d:propfind>"
        )
        headers = {
            "Depth": "1",
            "Content-Type": "application/xml; charset=utf-8",
            "Accept": "application/xml, text/xml",
        }
        response = session.request(
            "PROPFIND", url, data=body, headers=headers, timeout=self.timeout
        )
        response.raise_for_status()

        root = ET.fromstring(response.content)
        addressbooks = []
        for response_node in root.findall(f"{{{_DAV_NS}}}response"):
            href_el = response_node.find(f"{{{_DAV_NS}}}href")
            if href_el is None or not href_el.text:
                continue
            if self._is_addressbook(response_node):
                addressbooks.append(urljoin(url, href_el.text.strip()))
        return addressbooks

    def _is_addressbook(self, response_node: ET.Element) -> bool:
        """Return True if a multistatus response node is a CardDAV address book."""
        for propstat in response_node.findall(f"{{{_DAV_NS}}}propstat"):
            resourcetype = propstat.find(f"{{{_DAV_NS}}}prop/{{{_DAV_NS}}}resourcetype")
            if (
                resourcetype is not None
                and resourcetype.find(f"{{{_CARDDAV_NS}}}addressbook") is not None
            ):
                return True
        return False

    def _report_addressbook(
        self, session: requests.Session, addressbook_url: str
    ) -> List[Dict[str, Any]]:
        """REPORT an addressbook-query asking for address-data and parse vCards."""
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<card:addressbook-query xmlns:d="{_DAV_NS}" '
            f'xmlns:card="{_CARDDAV_NS}">'
            "<d:prop><d:getetag/><card:address-data/></d:prop>"
            '<card:filter><card:prop-filter name="FN"/></card:filter>'
            "</card:addressbook-query>"
        )
        headers = {
            "Depth": "1",
            "Content-Type": "application/xml; charset=utf-8",
            "Accept": "text/vcard, application/xml",
        }
        response = session.request(
            "REPORT", addressbook_url, data=body, headers=headers, timeout=self.timeout
        )
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        if content_type.startswith("text/vcard") or content_type.startswith(
            "text/x-vcard"
        ):
            return self._parse_vcards_text(response.text, addressbook_url)
        return self._extract_vcards_from_multistatus(response.content, addressbook_url)

    def _extract_vcards_from_multistatus(
        self, content: bytes, addressbook_url: str
    ) -> List[Dict[str, Any]]:
        """Extract and parse ``address-data`` values from a multistatus response."""
        root = ET.fromstring(content)
        raw_contacts = []
        for response_node in root.findall(f"{{{_DAV_NS}}}response"):
            href_el = response_node.find(f"{{{_DAV_NS}}}href")
            href = (
                href_el.text.strip()
                if href_el is not None and href_el.text
                else addressbook_url
            )
            for propstat in response_node.findall(f"{{{_DAV_NS}}}propstat"):
                address_data = propstat.find(
                    f"{{{_DAV_NS}}}prop/{{{_CARDDAV_NS}}}address-data"
                )
                if address_data is not None and address_data.text:
                    raw_contacts.extend(
                        self._parse_vcards_text(address_data.text, href)
                    )
        return raw_contacts

    def _parse_vcards_text(self, text: str, source_url: str) -> List[Dict[str, Any]]:
        """Parse one or more vCards from a text body into raw contact dicts.

        vCards are split on ``BEGIN:VCARD``/``END:VCARD`` boundaries so a
        single malformed vCard is skipped without failing the run (FR-009).
        """
        raw_contacts = []
        for card_text in self._split_vcards(text):
            try:
                vcard = vobject.readOne(card_text)
            except Exception as e:
                self.logger.warning(
                    f"Skipping unparseable vCard from {source_url}: {e}"
                )
                continue
            raw_contacts.append({"url": source_url, "data": vcard})
        return raw_contacts

    @staticmethod
    def _split_vcards(text: str) -> List[str]:
        """Split a body of concatenated vCards into individual vCard texts.

        Line endings and leading whitespace are preserved so vCard line folding
        (RFC 6350 §3.2) stays intact when each card is parsed by vobject. The
        old version stripped lines, which destroyed folded continuation lines
        and made vobject reject the whole card (e.g. contacts with photos).
        """
        cards = []
        current = None
        for raw_line in text.splitlines():
            line = raw_line.rstrip("\r")
            upper = line.strip().upper()
            if upper.startswith("BEGIN:VCARD"):
                current = [line]
            elif current is not None:
                current.append(line)
                if upper.startswith("END:VCARD"):
                    cards.append("\n".join(current))
                    current = None
        if current is not None:
            # Unclosed block: attempt to parse it anyway.
            cards.append("\n".join(current))
        return cards

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

        self.logger.debug(
            f"Parsed vCard for contact '{name}' from source priority {source_priority}"
        )
        return contact

    def _extract_formatted_name(self, vcard: vCard) -> str:
        """Extract and format contact name from vCard.

        Args:
            vcard: vCard object to parse

        Returns:
            Formatted contact name string
        """
        # Try to get formatted name (FN) first
        fn_list = vcard.contents.get("fn")
        if fn_list and getattr(fn_list[0], "value", None):
            return fn_list[0].value

        # Fall back to structured name (N)
        n_list = vcard.contents.get("n")
        if n_list:
            n = n_list[0].value
            given = getattr(n, "given", "") or ""
            family = getattr(n, "family", "") or ""
            if given and family:
                return f"{given} {family}"
            return given or family or "Unknown Contact"

        # Ultimate fallback: Use UID if available
        uid_list = vcard.contents.get("uid")
        if uid_list:
            return uid_list[0].value

        return "Unknown Contact"

    def _extract_phone_numbers(self, vcard: vCard) -> List[PhoneNumber]:
        """Extract and format phone numbers from vCard.

        Args:
            vcard: vCard object to parse

        Returns:
            List of PhoneNumber objects
        """
        phone_numbers = []
        tel_properties = vcard.contents.get("tel") or []

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
        types = tel.params.get("TYPE", []) if hasattr(tel, "params") else []
        for t in types:
            t = t.lower()
            if t in ("home", "work", "mobile", "cell", "fax", "pager"):
                return "mobile" if t == "cell" else t

        # Try to infer from value
        if tel.value.startswith("+"):
            return "mobile"
        elif "home" in str(tel).lower():
            return "home"
        elif "work" in str(tel).lower():
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
        email_properties = vcard.contents.get("email") or []

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
        types = email.params.get("TYPE", []) if hasattr(email, "params") else []
        if any(t.lower() in ("work", "office") for t in types):
            return "work"

        # Try to infer from value
        if "work" in str(email).lower():
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
        photo_list = vcard.contents.get("photo")
        if not photo_list:
            return None, None

        # Handle different photo formats
        photo = photo_list[0]
        photo_value = photo.value
        params = photo.params if hasattr(photo, "params") else {}
        value_types = [v.lower() for v in params.get("VALUE", [])]

        if "uri" in value_types or (
            isinstance(photo_value, str)
            and photo_value.startswith(("http://", "https://", "ftp://"))
        ):
            # Photo is a URL
            return None, photo_value

        if isinstance(photo_value, bytes):
            # vobject already decoded inline base64 data
            return photo_value, None

        if isinstance(photo_value, str):
            try:
                import base64

                return base64.b64decode(photo_value), None
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
        categories = vcard.contents.get("categories")
        if categories:
            values = categories[0].value
            if isinstance(values, list):
                lowered = [str(v).lower() for v in values]
            else:
                lowered = [str(values).lower()]
            return any("vip" in value or "important" in value for value in lowered)

        return False

    def _extract_unique_id(self, vcard: vCard) -> Optional[int]:
        """Extract unique ID from vCard.

        Args:
            vcard: vCard object to parse

        Returns:
            Integer unique ID if available, None otherwise
        """
        uid_list = vcard.contents.get("uid")
        if uid_list:
            # Try to extract numeric ID from UID
            uid_value = uid_list[0].value
            # Extract numbers from UID string
            import re

            numbers = re.findall(r"\d+", str(uid_value))
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

            # Prefer the configured source priority (FR-013); fall back to a
            # URL heuristic for callers that do not provide one.
            source_priority = raw_contact.get("source_priority") or (
                self._extract_source_priority_from_url(raw_contact["url"])
            )

            contact = self.parse_vcard_to_contact(vcard, source_priority)
            parsed_contacts.append(contact)

        self.logger.info(
            f"Successfully parsed {len(parsed_contacts)} contacts from vCard data"
        )
        return parsed_contacts

    def merge_contacts(self, contacts: List[Contact]) -> List[Contact]:
        """Merge duplicate contacts from different sources by identity (FR-004).

        Sources are fetched in priority order, so the first encounter of an
        identity wins; multi-value fields (phones, emails) from later sources
        are appended to it (FR-004/FR-013). Identity uses the canonical
        normalized phone/email form (FR-018).

        Args:
            contacts: Parsed contact objects from one or more sources.

        Returns:
            Contacts with cross-source duplicates merged into one entry.
        """
        regional = self.config.regional
        merged: List[Contact] = []
        for contact in contacts:
            existing_idx = next(
                (
                    i
                    for i, existing in enumerate(merged)
                    if existing.is_duplicate_of(
                        contact,
                        self.config.general.name_order,
                        regional.country_code,
                        regional.area_code,
                        regional.international_access_code,
                    )
                ),
                None,
            )
            if existing_idx is None:
                merged.append(contact)
            else:
                merged[existing_idx].merge_with(
                    contact,
                    regional.country_code,
                    regional.area_code,
                    regional.international_access_code,
                )

        self.logger.info(
            f"Merged {len(contacts)} contacts into {len(merged)} unique contacts"
        )
        return merged

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

        Performs a Depth-0 PROPFIND against the configured URL to verify the
        endpoint is reachable and authentication succeeds.

        Args:
            source_config: CardDAV source configuration to test

        Returns:
            True if the connection test succeeds, False otherwise
        """
        try:
            session = self._session_for(source_config)
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<d:propfind xmlns:d="{_DAV_NS}">'
                "<d:prop><d:resourcetype/></d:prop>"
                "</d:propfind>"
            )
            headers = {
                "Depth": "0",
                "Content-Type": "application/xml; charset=utf-8",
                "Accept": "application/xml, text/xml",
            }
            response = session.request(
                "PROPFIND",
                source_config.url,
                data=body,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            self.logger.info(
                f"Test connection successful for source: {source_config.url}"
            )
            return True
        except requests.RequestException as e:
            self.logger.error(
                f"Test connection failed for source {source_config.url}: {e}"
            )
            return False
