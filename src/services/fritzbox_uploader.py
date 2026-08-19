"""FritzBox uploader module for CardDAV to FritzBox sync utility.

This module provides functionality to upload contacts to a FritzBox device
and manage authentication with the FritzBox HTTP API.

Key features:
- Challenge-response authentication using login_sid.lua
- Multipart POST upload to /cgi-bin/firmwarecfg for mirror sync
- XML document generation according to FritzBox schema
- Comprehensive error handling and logging
- Session management with automatic re-authentication
"""

import base64
import hashlib
import logging
import requests
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from io import BytesIO
from xml.dom import minidom

from src.models.contact import Contact, PhoneNumber, EmailAddress
from src.config.loader import FritzBoxConfig


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


class FritzBoxUploader:
    """Handles authentication and contact upload to FritzBox devices.

    The uploader supports:
    1. Challenge-response authentication via login_sid.lua
    2. Full phonebook overwrite via /cgi-bin/firmwarecfg (mirror sync)
    3. XML document generation according to FritzBox schema
    4. Automatic session management and re-authentication
    5. Comprehensive error handling and logging

    Args:
        config: FritzBox configuration containing connection details
        logger: Logger instance for logging operations
    """

    def __init__(self, config: FritzBoxConfig, logger: logging.Logger):
        """Initialize the FritzBox uploader.

        Args:
            config: FritzBox configuration
            logger: Logger instance
        """
        self.config = config
        self.logger = logger
        self.session_id: Optional[str] = None
        self.host = config.host

    def authenticate(self) -> bool:
        """Authenticate with FritzBox using challenge-response mechanism.

        Returns:
            True if authentication succeeds, False otherwise
        """
        try:
            url = f"http://{self.host}/login_sid.lua"

            # Step 1: Get challenge
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
            params = {
                "username": self.config.username,
                "response": challenge_response
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            login_tree = ET.fromstring(response.content)
            self.session_id = login_tree.findtext("SID")

            if self.session_id == "0000000000000000":
                raise PermissionError("FritzBox authentication failed. Check credentials.")

            self.logger.info(f"Authentication successful, session ID: {self.session_id}")
            return True

        except Exception as e:
            self.logger.error(f"FritzBox authentication failed: {e}")
            return False

    def _calculate_challenge_response(self, challenge: str) -> str:
        """Calculate MD5 challenge-response using UTF-16LE encoding.

        Args:
            challenge: Challenge string from FritzBox

        Returns:
            Challenge-response string in format "<Challenge>-<md5_hash>"
        """
        # MD5 Challenge Response Calculation (UTF-16LE)
        hash_input = f"{challenge}-{self.config.password}".encode("utf-16le")
        md5_hash = hashlib.md5(hash_input).hexdigest()
        return f"{challenge}-{md5_hash}"

    def upload_phonebook(self, contacts: List[Contact], phonebook_name: str,
                        phonebook_id: int = 0) -> bool:
        """Upload contacts to FritzBox using mirror sync (overwrite).

        This method implements FR-011 and FR-012: mirror sync with complete overwrite.

        Args:
            contacts: List of Contact objects to upload
            phonebook_name: Name of the target phonebook in FritzBox
            phonebook_id: ID of the phonebook (0 for default, 1, 2, etc.)

        Returns:
            True if upload succeeds, False otherwise
        """
        try:
            if not self.session_id:
                if not self.authenticate():
                    return False

            # Generate XML document
            phonebook_xml = self._generate_phonebook_xml(contacts, phonebook_name)

            # Upload via multipart/form-data
            success = self._upload_to_fritzbox(phonebook_xml, phonebook_name, phonebook_id)

            if success:
                self.logger.info(f"Successfully uploaded {len(contacts)} contacts to FritzBox")
            else:
                self.logger.error("Failed to upload contacts to FritzBox")

            return success

        except Exception as e:
            self.logger.error(f"Error during FritzBox upload: {e}")
            return False

    def _generate_phonebook_xml(self, contacts: List[Contact], phonebook_name: str) -> str:
        """Generate FritzBox phonebook XML document from Contact objects.

        Args:
            contacts: List of Contact objects to convert
            phonebook_name: Name for the phonebook

        Returns:
            XML document as string
        """
        phonebook_xml = PhonebookXML(name=phonebook_name)

        # Convert each Contact to ContactXML
        for i, contact in enumerate(contacts):
            contact_xml = self._convert_contact_to_xml(contact)
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

                for phone in contact_xml.phone_numbers:
                    number_elem = ET.SubElement(telephony_elem, "number")
                    number_elem.set("type", phone.type)
                    number_elem.set("prio", str(phone.prio))
                    number_elem.set("id", str(phone.prio))
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
        setup_elem = ET.SubElement(phonebook_elem, "setup")
        features_elem = ET.SubElement(phonebook_elem, "features")
        features_elem.set("doorphone", "0")

        # Pretty print the XML
        xml_str = ET.tostring(root, encoding='utf-8')
        return self._pretty_print_xml(xml_str)

    def _convert_contact_to_xml(self, contact: Contact) -> ContactXML:
        """Convert a Contact object to ContactXML.

        Args:
            contact: Contact object to convert

        Returns:
            ContactXML object
        """
        contact_xml = ContactXML(
            name=contact.name,
            category="1" if contact.is_vip else "0",
            image_url=contact.picture_url
        )

        # Convert phone numbers
        for phone in contact.phone_numbers:
            contact_xml.phone_numbers.append(PhoneNumber(
                number=phone.number,
                type=phone.type,
                prio=phone.prio,
                quickdial=phone.quickdial,
                vanity=phone.vanity
            ))

        # Convert email addresses
        for email in contact.emails:
            contact_xml.email_addresses.append(EmailAddress(
                email=email.email,
                classifier=email.classifier
            ))

        contact_xml.unique_id = contact.unique_id
        return contact_xml

    def _pretty_print_xml(self, xml_bytes: bytes) -> str:
        """Format XML with proper indentation.

        Args:
            xml_bytes: XML content as bytes

        Returns:
            Pretty-printed XML as string
        """
        try:
            dom = minidom.parseString(xml_bytes.decode('utf-8'))
            return dom.toprettyxml(indent="  ", encoding='utf-8').decode('utf-8')
        except:
            # Fallback to simple formatting
            return xml_bytes.decode('utf-8')

    def _upload_to_fritzbox(self, xml_content: str, phonebook_name: str, phonebook_id: int) -> bool:
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
                'sid': (None, self.session_id),
                'PhonebookId': (None, str(phonebook_id)),
                'PhonebookImportName': (None, phonebook_name),
                'PhonebookImportFile': (
                    'phonebook.xml',
                    xml_content.encode('utf-8'),
                    'text/xml'
                )
            }

            response = requests.post(url, files=files, timeout=30)
            response.raise_for_status()

            # Parse response
            response_xml = ET.fromstring(response.content)
            success = response_xml.findtext("success") == "1"

            if success:
                self.logger.info(f"Successfully uploaded phonebook '{phonebook_name}' to FritzBox")
            else:
                error_msg = response_xml.findtext("error") or "Unknown error"
                self.logger.error(f"FritzBox upload failed: {error_msg}")

            return success

        except Exception as e:
            self.logger.error(f"Error uploading to FritzBox: {e}")
            return False

    def test_connection(self) -> bool:
        """Test connection to FritzBox.

        Returns:
            True if connection test succeeds, False otherwise
        """
        try:
            url = f"http://{self.host}/login_sid.lua"
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            tree = ET.fromstring(response.content)
            sid = tree.findtext("SID")

            if sid == "0000000000000000":
                return False

            return True

        except Exception as e:
            self.logger.error(f"FritzBox connection test failed: {e}")
            return False


class XMLGenerator:
    """Utility class for generating FritzBox-compatible XML documents.

    Provides methods for:
    - Generating phonebook XML from contact lists
    - Formatting XML with proper indentation
    - Validating XML structure
    """

    @staticmethod
    def generate_phonebook_xml(phonebook_name: str, contacts: List[Contact],
                               phonebook_id: int = 0) -> str:
        """Generate complete phonebook XML document.

        Args:
            phonebook_name: Name for the phonebook
            contacts: List of contacts to include
            phonebook_id: Phonebook ID (default: 0)

        Returns:
            Formatted XML string
        """
        uploader = FritzBoxUploader(
            FritzBoxConfig(
                url=f"http://{phonebook_name}",
                username="",
                password="",
                target_book=""
            ),
            logging.getLogger(__name__)
        )

        return uploader._generate_phonebook_xml(contacts, phonebook_name)

    @staticmethod
    def validate_xml_structure(xml_content: str) -> Tuple[bool, str]:
        """Validate XML structure against FritzBox requirements.

        Args:
            xml_content: XML content to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            root = ET.fromstring(xml_content)

            # Check root element
            if root.tag != "phonebooks":
                return False, "Root element must be 'phonebooks'"

            # Check phonebook element
            phonebook = root.find("phonebook")
            if phonebook is None:
                return False, "Missing phonebook element"

            # Check required attributes
            if "name" not in phonebook.attrib:
                return False, "Phonebook element must have 'name' attribute"

            return True, "XML structure is valid"

        except ET.ParseError as e:
            return False, f"Invalid XML: {e}"
        except Exception as e:
            return False, f"XML validation error: {e}"


def example_usage():
    """Example demonstrating how to use FritzBoxUploader."""
    import logging

    # Setup logger
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)

    # Mock configuration
    config = FritzBoxConfig(
        url="https://fritz.box",
        username="test_user",
        password="test_password",
        target_book="CardDAV Sync"
    )

    # Create uploader
    uploader = FritzBoxUploader(config, logger)

    # Test connection
    print("Testing FritzBox connection...")
    if uploader.test_connection():
        print("Connection test: PASSED")
    else:
        print("Connection test: FAILED")

    # Example contact list
    contacts = [
        Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+1234567890", type="home", prio=1)],
            emails=[EmailAddress(email="john@example.com", classifier="private")]
        ),
        Contact(
            name="Jane Smith",
            phone_numbers=[
                PhoneNumber(number="+442071234567", type="mobile", prio=1),
                PhoneNumber(number="+44203456789", type="work", prio=0)
            ],
            emails=[EmailAddress(email="jane@company.com", classifier="work")]
        )
    ]

    # Upload phonebook
    print("\nUploading phonebook to FritzBox...")
    if uploader.upload_phonebook(contacts, "CardDAV Sync", 0):
        print("Phonebook upload: SUCCESS")
    else:
        print("Phonebook upload: FAILED")

    # Test authentication
    print("\nTesting authentication...")
    if uploader.authenticate():
        print("Authentication: SUCCESS")
    else:
        print("Authentication: FAILED")


if __name__ == "__main__":
    example_usage()
