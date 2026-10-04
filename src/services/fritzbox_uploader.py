"""FritzBox uploader module for CardDAV to FritzBox sync utility.

This module provides functionality to upload contacts to a FritzBox device
and manage authentication with the FritzBox HTTP API.

Key features:
- Challenge-response authentication using login_sid.lua (MD5 legacy path and
  PBKDF2-HMAC-SHA256 for FRITZ!OS 7.24+, research.md section 2.1)
- Multipart POST upload to /cgi-bin/firmwarecfg for mirror sync
- XML document generation according to FritzBox schema
- Contact picture sync (FR-020): converted JPEGs are uploaded over FTP into
  the box's fonpix directory and referenced via a file:/// URL
- Comprehensive error handling and logging
- Session management with automatic re-authentication
"""

import hashlib
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from xml.dom import minidom

import requests

from src.config.loader import FritzBoxConfig
from src.models.contact import Contact, EmailAddress, PhoneNumber
from src.services.converter import PhoneNumberNormalizer
from src.services.fritzbox_images import FritzBoxImageUploader, image_key
from src.services.tr064 import Tr064Client

# FritzBox XML schema limits (contracts/fritzbox-api.md, research.md section 4):
# at most 9 phone numbers (id 0-8) and 2 email addresses (private, work) per
# contact; exactly one number carries prio="1".
_MAX_PHONE_NUMBERS = 9
_MAX_EMAIL_ADDRESSES = 2


@dataclass
class FritzBoxAuthentication:
    """Authentication credentials for FritzBox connection."""

    username: str
    password: str
    host: str = "fritz.box"


@dataclass
class ContactXML:
    """Represents a single contact in FritzBox XML format."""

    name: str
    category: str = "0"
    image_url: Optional[str] = None
    phone_numbers: List[PhoneNumber] = field(default_factory=list)
    email_addresses: List[EmailAddress] = field(default_factory=list)
    unique_id: Optional[int] = None
    mod_time: int = 0


@dataclass
class PhonebookXML:
    """Represents a complete phonebook in FritzBox XML format."""

    name: str
    owner: str = "0"
    contacts: List[ContactXML] = field(default_factory=list)


_PB_SUCCESS_MARKERS = (
    "wurde wiederhergestellt",
    "is hersteld",
    "wurde wiederhergestellt",
    "was restored",
    "phonebook restored",
)

_PB_ERROR_MARKERS = (
    "invalid variable name",
    "mislukt",
    "failed",
    "fehlgeschlagen",
    "fehler",
)


class FritzBoxUploader:
    """Handles authentication and contact upload to FritzBox devices.

    The uploader supports:
    1. Challenge-response authentication via login_sid.lua (MD5 and PBKDF2)
    2. Full phonebook overwrite via /cgi-bin/firmwarecfg (mirror sync)
    3. XML document generation according to FritzBox schema
    4. Automatic session management and re-authentication
    5. Comprehensive error handling and logging

    Args:
        config: FritzBox configuration containing connection details
        logger: Logger instance for logging operations
    """

    def __init__(
        self,
        config: FritzBoxConfig,
        logger: logging.Logger,
        normalizer: Optional[PhoneNumberNormalizer] = None,
        name_order: str = "first_name_first",
    ):
        """Initialize the FritzBox uploader.

        Args:
            config: FritzBox configuration
            logger: Logger instance
            normalizer: Optional PhoneNumberNormalizer used to shorten numbers
                at export time (FR-006). When None, numbers are uploaded in
                their canonical form.
            name_order: Name ordering for the ``<realName>`` export
                (FR-015): ``first_name_first`` ("First Last") or
                ``last_name_first`` ("Last, First").
        """
        self.config = config
        self.logger = logger
        self.session_id: Optional[str] = None
        self.host = config.host
        self.normalizer = normalizer
        self.name_order = name_order

    def authenticate(self) -> bool:
        """Authenticate with FritzBox using challenge-response mechanism.

        Returns:
            True if authentication succeeds, False otherwise
        """
        try:
            # Step 1: Get challenge (version=2 requests the PBKDF2 challenge on
            # FRITZ!OS 7.24+; older firmware returns the legacy MD5 challenge)
            url = f"http://{self.host}/login_sid.lua?version=2"

            response = requests.get(url, timeout=10)
            response.raise_for_status()

            tree = ET.fromstring(response.content)
            challenge = tree.findtext("Challenge")
            sid = tree.findtext("SID")

            # Check if we already have a valid session
            if sid and sid != "0000000000000000":
                self.session_id = sid
                self.logger.info(f"Using existing session ID: {sid}")
                return True

            # Step 2: Calculate challenge-response
            challenge_response = self._calculate_challenge_response(challenge)

            # Step 3: Submit response
            params = {"username": self.config.username, "response": challenge_response}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            login_tree = ET.fromstring(response.content)
            self.session_id = login_tree.findtext("SID")

            if self.session_id == "0000000000000000":
                raise PermissionError(
                    "FritzBox authentication failed. Check credentials."
                )

            self.logger.info(
                f"Authentication successful, session ID: {self.session_id}"
            )
            return True

        except Exception as e:
            self.logger.error(f"FritzBox authentication failed: {e}")
            return False

    def _calculate_challenge_response(self, challenge: str) -> str:
        """Calculate the challenge-response for a given FritzBox challenge.

        Dispatches to the PBKDF2-HMAC-SHA256 scheme when the challenge carries
        the ``2$`` prefix (FRITZ!OS 7.24+); otherwise falls back to the legacy
        MD5 scheme (research.md section 2.1).

        Args:
            challenge: Challenge string from FritzBox

        Returns:
            Challenge-response string

        Raises:
            ValueError: On a malformed PBKDF2 challenge
        """
        if challenge.startswith("2$"):
            return self._calculate_pbkdf2_response(challenge)
        return self._calculate_md5_response(challenge)

    def _calculate_md5_response(self, challenge: str) -> str:
        """Calculate the legacy MD5 challenge-response using UTF-16LE encoding.

        Args:
            challenge: Challenge string from FritzBox

        Returns:
            Challenge-response string in format "<Challenge>-<md5_hash>"
        """
        # MD5 Challenge Response Calculation (UTF-16LE)
        hash_input = f"{challenge}-{self.config.password}".encode("utf-16le")
        md5_hash = hashlib.md5(hash_input).hexdigest()
        return f"{challenge}-{md5_hash}"

    def _calculate_pbkdf2_response(self, challenge: str) -> str:
        """Calculate the PBKDF2-HMAC-SHA256 challenge-response (FRITZ!OS 7.24+).

        Challenge format: ``2$<iter1>$<salt1>$<iter2>$<salt2>`` with hex
        encoded salts. The password is hashed against the static salt, then the
        raw (non-stringified) hash is hashed again against the dynamic salt.
        Response format: ``<salt2>$<hash2_hex>`` (AVM session ID spec).

        Args:
            challenge: PBKDF2 challenge string (prefix ``2$``)

        Returns:
            Challenge-response string in format "<salt2>$<hash2>"

        Raises:
            ValueError: On a malformed PBKDF2 challenge
        """
        parts = challenge.split("$")
        if len(parts) != 5:
            raise ValueError(
                f"Malformed PBKDF2 challenge (expected "
                f"'2$<iter1>$<salt1>$<iter2>$<salt2>'): {challenge!r}"
            )
        iterations_1 = int(parts[1])
        salt_1 = bytes.fromhex(parts[2])
        iterations_2 = int(parts[3])
        salt_2 = bytes.fromhex(parts[4])

        hash_1 = hashlib.pbkdf2_hmac(
            "sha256", self.config.password.encode(), salt_1, iterations_1
        )
        hash_2 = hashlib.pbkdf2_hmac("sha256", hash_1, salt_2, iterations_2)
        return f"{parts[4]}${hash_2.hex()}"

    def upload_phonebook(
        self,
        contacts: List[Contact],
        phonebook_name: str,
        phonebook_id: Optional[int] = None,
    ) -> bool:
        """Upload contacts to FritzBox using mirror sync (overwrite).

        This method implements FR-011 and FR-012: mirror sync with complete overwrite.

        When ``phonebook_id`` is ``None`` the target book is resolved by name
        (``config.target_book``) via TR-064; the book is created when it does
        not exist yet. When TR-064 is unavailable the main phonebook (0) is
        used as a fallback.

        Args:
            contacts: List of Contact objects to upload
            phonebook_name: Name of the target phonebook in FritzBox
            phonebook_id: ID of the phonebook (None to resolve by name)

        Returns:
            True if upload succeeds, False otherwise
        """
        try:
            if not self.session_id:
                if not self.authenticate():
                    return False

            target_id = self._resolve_phonebook_id(phonebook_id)

            # Contacts without phone numbers cannot be stored by the FritzBox
            # import (verified: firmwarecfg silently drops them), so skip them
            # with a warning so the reported count matches the box.
            for contact in contacts:
                if not contact.phone_numbers:
                    self.logger.warning(
                        f"Skipping contact without a phone number: {contact.name}"
                    )
            contacts = [c for c in contacts if c.phone_numbers]

            # Contact picture sync (FR-020): upload converted JPEGs into the
            # box's fonpix directory over FTP and reference them via file:///
            # URLs. Without fonpix_dir/imagepath configured pictures are
            # skipped with a warning (embedded data URIs are not resolved by
            # the box). When pictures are to be synced, the FTP picture
            # directory is verified first: if it is unavailable the sync is
            # aborted before anything is uploaded so the existing phonebook
            # stays intact (FR-021).
            image_urls: Optional[Dict[str, str]] = None
            if self._image_sync_configured():
                if any(c.picture_data for c in contacts):
                    image_uploader = self._build_image_uploader()
                    if not image_uploader.check_directory():
                        self.logger.error(
                            "Aborting sync: the FTP picture directory is not "
                            "available; the existing phonebook was left "
                            "untouched (FR-021)."
                        )
                        return False
                    image_urls = image_uploader.sync_images(contacts)
            elif any(c.picture_data for c in contacts):
                self.logger.warning(
                    "Contact pictures present but image sync is not configured; "
                    "set fritzbox.fonpix_dir and fritzbox.imagepath to upload "
                    "pictures via FTP (FR-020)."
                )

            # Generate XML document
            phonebook_xml = self._generate_phonebook_xml(
                contacts, phonebook_name, image_urls
            )

            # Upload via multipart/form-data
            success = self._upload_to_fritzbox(phonebook_xml, phonebook_name, target_id)

            if success:
                self.logger.info(
                    f"Successfully uploaded {len(contacts)} contacts to FritzBox"
                )
            else:
                self.logger.error("Failed to upload contacts to FritzBox")

            return success

        except Exception as e:
            self.logger.error(f"Error during FritzBox upload: {e}")
            return False

    def _resolve_phonebook_id(self, phonebook_id: Optional[int]) -> int:
        """Resolve the phonebook id to upload into.

        An explicit ``phonebook_id`` wins. Otherwise the book is resolved by
        name via TR-064 (creating it when missing); when TR-064 is not
        available the main phonebook (0) is returned as a fallback.

        Args:
            phonebook_id: Explicit phonebook id, or None to resolve by name

        Returns:
            The phonebook id to upload into
        """
        if phonebook_id is not None:
            return phonebook_id

        try:
            client = Tr064Client(
                self.host,
                self.config.username,
                self.config.password,
                self.logger,
            )
            resolved = client.resolve_phonebook_id(self.config.target_book)
        except Exception as e:
            self.logger.warning(
                f"TR-064 phonebook resolution failed: {e}; "
                "falling back to the main phonebook (0)"
            )
            return 0

        if resolved is not None:
            self.logger.info(
                f"Resolved target phonebook '{self.config.target_book}' "
                f"to phonebook id {resolved}"
            )
            return resolved

        self.logger.warning(
            "Could not resolve the target phonebook by name; "
            "falling back to the main phonebook (0)"
        )
        return 0

    def _generate_phonebook_xml(
        self,
        contacts: List[Contact],
        phonebook_name: str,
        image_urls: Optional[Dict[str, str]] = None,
    ) -> str:
        """Generate FritzBox phonebook XML document from Contact objects.

        Args:
            contacts: List of Contact objects to convert
            phonebook_name: Name for the phonebook
            image_urls: Optional mapping of contact key to the uploaded
                ``file:///`` picture URL (FR-020). When present, inline
                ``picture_data`` is referenced through it.

        Returns:
            XML document as string
        """
        phonebook_xml = PhonebookXML(name=phonebook_name)

        # Convert each Contact to ContactXML
        for i, contact in enumerate(contacts):
            contact_xml = self._convert_contact_to_xml(contact, image_urls)
            contact_xml.mod_time = int(time.time())
            contact_xml.unique_id = i + 1
            phonebook_xml.contacts.append(contact_xml)

        # Generate XML document
        root = ET.Element("phonebooks")
        phonebook_elem = ET.SubElement(root, "phonebook")
        phonebook_elem.set("name", phonebook_xml.name)
        phonebook_elem.set("owner", phonebook_xml.owner)

        for contact_xml in phonebook_xml.contacts:
            contact_elem = ET.SubElement(phonebook_elem, "contact")
            contact_elem.set("category", contact_xml.category)

            # Add person section
            person_elem = ET.SubElement(contact_elem, "person")
            real_name_elem = ET.SubElement(person_elem, "realName")
            real_name_elem.text = contact_xml.name

            if contact_xml.image_url:
                image_url_elem = ET.SubElement(person_elem, "imageURL")
                image_url_elem.text = contact_xml.image_url

            # Add telephony section
            if contact_xml.phone_numbers:
                telephony_elem = ET.SubElement(contact_elem, "telephony")
                telephony_elem.set("nid", str(len(contact_xml.phone_numbers)))

                for idx, phone in enumerate(contact_xml.phone_numbers):
                    number_elem = ET.SubElement(telephony_elem, "number")
                    number_elem.set("type", phone.type)
                    number_elem.set("prio", str(phone.prio))
                    number_elem.set("id", str(idx))
                    number_elem.set("quickdial", phone.quickdial)
                    number_elem.set("vanity", phone.vanity)
                    number_elem.text = phone.number

            # Add services section
            if contact_xml.email_addresses:
                services_elem = ET.SubElement(contact_elem, "services")
                for i, email in enumerate(contact_xml.email_addresses):
                    email_elem = ET.SubElement(services_elem, "email")
                    email_elem.set("classifier", email.classifier)
                    email_elem.set("id", str(i))
                    email_elem.text = email.email

            # Add mod_time and uniqueid
            mod_time_elem = ET.SubElement(contact_elem, "mod_time")
            mod_time_elem.text = str(contact_xml.mod_time)

            uniqueid_elem = ET.SubElement(contact_elem, "uniqueid")
            uniqueid_elem.text = str(contact_xml.unique_id)

        # Add setup and features elements
        ET.SubElement(phonebook_elem, "setup")
        features_elem = ET.SubElement(phonebook_elem, "features")
        features_elem.set("doorphone", "0")

        # Pretty print the XML
        xml_str = ET.tostring(root, encoding="utf-8")
        return self._pretty_print_xml(xml_str)

    def _convert_contact_to_xml(
        self, contact: Contact, image_urls: Optional[Dict[str, str]] = None
    ) -> ContactXML:
        """Convert a Contact object to ContactXML.

        Args:
            contact: Contact object to convert
            image_urls: Optional mapping of contact key to the uploaded
                ``file:///`` picture URL (FR-020).

        Returns:
            ContactXML object
        """
        contact_xml = ContactXML(
            name=contact.get_display_name(self.name_order),
            category="1" if contact.is_vip else "0",
            image_url=self._image_url_for(contact, image_urls),
        )

        # Phone numbers (shortened for FritzBox at export time, FR-006).
        # FritzBox stores at most 9 numbers per contact (id 0-8) with exactly
        # one prio="1" (the first number); excess numbers are dropped with a
        # warning (contracts/fritzbox-api.md, research.md section 4).
        phones = contact.phone_numbers[:_MAX_PHONE_NUMBERS]
        for skipped in contact.phone_numbers[_MAX_PHONE_NUMBERS:]:
            self.logger.warning(
                f"Skipping extra phone number for {contact.name}: {skipped.number}"
            )
        for idx, phone in enumerate(phones):
            number = phone.number
            if self.normalizer is not None:
                number = self.normalizer.format_for_fritzbox(number)
            contact_xml.phone_numbers.append(
                PhoneNumber(
                    number=number,
                    type=phone.type,
                    prio=1 if idx == 0 else 0,
                    quickdial=phone.quickdial,
                    vanity=phone.vanity,
                )
            )

        # Email addresses: FritzBox stores at most 2 per contact (one
        # "private", one "work"); excess addresses are dropped with a warning
        # (contracts/fritzbox-api.md, research.md section 4).
        emails_by_classifier = {}
        for email in contact.emails:
            if len(emails_by_classifier) >= _MAX_EMAIL_ADDRESSES:
                continue
            classifier = (
                email.classifier
                if email.classifier in ("private", "work")
                else "private"
            )
            emails_by_classifier.setdefault(classifier, email)
        skipped_emails = len(contact.emails) - len(emails_by_classifier)
        if skipped_emails > 0:
            self.logger.warning(
                f"Skipping {skipped_emails} extra email address(es) for "
                f"{contact.name}"
            )
        contact_xml.email_addresses = list(emails_by_classifier.values())

        contact_xml.unique_id = contact.unique_id
        return contact_xml

    def _image_url_for(
        self, contact: Contact, image_urls: Optional[Dict[str, str]] = None
    ) -> Optional[str]:
        """Return the ``<imageURL>`` value for a contact (FR-020).

        Inline ``picture_data`` is referenced through the uploaded ``file:///``
        URL produced by :class:`~src.services.fritzbox_images.FritzBoxImageUploader`
        when image sync is configured (the box resolves ``<imageURL>`` to a
        file on its own storage and cannot display embedded data). When no
        upload succeeded, the picture is omitted. External photo URIs are
        written as-is.
        """
        if contact.picture_data:
            if image_urls:
                url = image_urls.get(image_key(contact))
                if url:
                    self.logger.debug(
                        f"Picture for '{contact.name}' "
                        f"(key {image_key(contact)}): using {url}"
                    )
                    return url
                self.logger.warning(
                    f"Picture for {contact.name} could not be uploaded; "
                    "omitting imageURL"
                )
            else:
                self.logger.debug(
                    f"Picture for '{contact.name}' "
                    f"(key {image_key(contact)}): no uploaded image "
                    "available, omitting imageURL"
                )
            return None
        if contact.picture_url:
            self.logger.debug(
                f"Picture for '{contact.name}': external URL " f"{contact.picture_url}"
            )
        return contact.picture_url

    def _image_sync_configured(self) -> bool:
        """True when both the FTP target dir and file:/// prefix are set."""
        return self.config.image_sync_configured

    def _build_image_uploader(self) -> FritzBoxImageUploader:
        """Build the FTP image uploader from the current configuration."""
        config = self.config
        return FritzBoxImageUploader(
            host=config.ftp_host or config.host,
            username=config.ftp_user or config.username,
            password=config.ftp_pass or config.password,
            fonpix_dir=config.fonpix_dir,
            imagepath=config.imagepath,
            plain=config.ftp_plain,
            logger=self.logger,
        )

    def _pretty_print_xml(self, xml_bytes: bytes) -> str:
        """Format XML with proper indentation.

        Args:
            xml_bytes: XML content as bytes

        Returns:
            Pretty-printed XML as string
        """
        try:
            dom = minidom.parseString(xml_bytes.decode("utf-8"))
            return dom.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
        except Exception:
            # Fallback to simple formatting
            return xml_bytes.decode("utf-8")

    def _upload_to_fritzbox(
        self, xml_content: str, phonebook_name: str, phonebook_id: int
    ) -> bool:
        """Upload XML phonebook to FritzBox via multipart/form-data.

        Args:
            xml_content: Phonebook XML content
            phonebook_name: Name of the phonebook
            phonebook_id: Phonebook ID

        Returns:
            True if upload succeeds, False otherwise
        """
        try:
            url = f"http://{self.host}/cgi-bin/firmwarecfg"

            files = {
                "sid": (None, self.session_id),
                "PhonebookId": (None, str(phonebook_id)),
                "PhonebookImportFile": (
                    "updatepb.xml",
                    xml_content.encode("utf-8"),
                    "text/xml",
                ),
            }

            response = requests.post(url, files=files, timeout=30)
            response.raise_for_status()

            # The FritzBox answers with an HTML page in the UI language
            # (e.g. "Das Telefonbuch der FRITZ!Box wurde wiederhergestellt."),
            # not XML, so success is detected via text markers (FR-011).
            body = response.text
            lowered = body.lower()

            if any(marker in lowered for marker in _PB_ERROR_MARKERS):
                self.logger.error(
                    f"FritzBox upload failed: {self._extract_message(body)}"
                )
                return False

            if any(marker in lowered for marker in _PB_SUCCESS_MARKERS):
                self.logger.info(
                    f"Successfully uploaded phonebook '{phonebook_name}' to FritzBox"
                )
                return True

            self.logger.error(
                f"FritzBox upload returned an unknown response: "
                f"{self._extract_message(body)}"
            )
            return False

        except Exception as e:
            self.logger.error(f"Error uploading to FritzBox: {e}")
            return False

    @staticmethod
    def _extract_message(html: str) -> str:
        """Extract a readable message from the FritzBox response page."""
        lowered = html.lower()
        for marker in _PB_ERROR_MARKERS:
            idx = lowered.find(marker)
            if idx >= 0:
                start = max(0, idx - 200)
                end = min(len(html), idx + 120)
                snippet = html[start:end].replace("\n", " ").strip()
                if snippet:
                    return snippet
        stripped = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", stripped).strip()[:300] or "Unknown error"

    def test_connection(self) -> bool:
        """Test connection to FritzBox.

        The probe only checks that the device is reachable and answers the
        ``login_sid.lua`` endpoint with a valid SessionInfo document. An
        unauthenticated session (``SID=0000000000000000``) is a normal
        pre-auth state and does not indicate a connection failure.

        Returns:
            True if connection test succeeds, False otherwise
        """
        try:
            url = f"http://{self.host}/login_sid.lua"
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            tree = ET.fromstring(response.content)
            sid = tree.findtext("SID")

            if sid is None:
                return False

            return True

        except Exception as e:
            self.logger.error(f"FritzBox connection test failed: {e}")
            return False
