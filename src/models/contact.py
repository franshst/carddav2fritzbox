"""Contact intermediate model representations."""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple


@dataclass
class PhoneNumber:
    number: str
    type: str = "home"  # "home", "mobile", "work", "fax"
    prio: int = 0  # 1 for primary number, 0 for secondary numbers
    quickdial: str = ""
    vanity: str = ""

    def normalize(self) -> "PhoneNumber":
        """Normalize phone number by stripping non-numeric characters except leading '+'."""
        self.number = re.sub(r'[^0-9+]', '', self.number)
        return self

    def is_primary(self) -> bool:
        """Check if this is the primary phone number."""
        return self.prio == 1

    def format_for_fritzbox(self) -> str:
        """Format phone number for FritzBox XML export."""
        return self.number

    @staticmethod
    def normalize_phone_number(phone: str) -> str:
        """Normalize a phone number string by stripping all non-numeric characters
        (preserving leading '+' for country/international detection).
        """
        return re.sub(r'[^0-9+]', '', phone)


@dataclass
class EmailAddress:
    email: str
    classifier: str = "private"  # "private" or "work"

    def is_primary(self) -> bool:
        """Check if this is the primary email address."""
        return self.classifier == "private"

    def format_for_fritzbox(self) -> Tuple[str, str]:
        """Format email address for FritzBox XML export."""
        return (self.email, self.classifier)


@dataclass
class Contact:
    name: str
    phone_numbers: List[PhoneNumber] = field(default_factory=list)
    emails: List[EmailAddress] = field(default_factory=list)
    picture_data: Optional[bytes] = None
    picture_url: Optional[str] = None
    is_vip: bool = False
    unique_id: Optional[int] = None

    def get_primary_phone(self) -> Optional[PhoneNumber]:
        """Get the primary phone number (prio=1), or the first phone if none marked as primary."""
        for phone in self.phone_numbers:
            if phone.is_primary():
                return phone
        return self.phone_numbers[0] if self.phone_numbers else None

    def get_primary_email(self) -> Optional[EmailAddress]:
        """Get the primary email address (classifier=\"private\"), or the first email if none marked as primary."""
        for email in self.emails:
            if email.is_primary():
                return email
        return self.emails[0] if self.emails else None

    def get_normalized_identity(self, name_order: str = "first_name_first") -> str:
        """Get contact identity string for merging: formatted name plus primary phone or email."""
        formatted_name = self._format_name(name_order)
        identity_parts = [formatted_name]

        primary_phone = self.get_primary_phone()
        if primary_phone:
            identity_parts.append(primary_phone.number)
        else:
            primary_email = self.get_primary_email()
            if primary_email:
                identity_parts.append(primary_email.email)

        return "|".join(identity_parts)

    def _format_name(self, name_order: str) -> str:
        """Format name according to the configured name order."""
        if name_order == "last_name_first":
            parts = self.name.split(" ", 1)
            if len(parts) == 2:
                return f"{parts[1]}, {parts[0]}"
        return self.name

    def add_phone(self, phone: PhoneNumber) -> None:
        """Add a phone number to the contact."""
        phone.normalize()
        self.phone_numbers.append(phone)

    def add_email(self, email: EmailAddress) -> None:
        """Add an email address to the contact."""
        self.emails.append(email)

    def merge_with(self, other: "Contact") -> "Contact":
        """Merge another contact into this one, following merge rules:
        - Name: Kept from this contact (canonical)
        - Multi-fields (phones, emails): Appended
        - Single-fields (picture): Kept from this contact
        """
        self.phone_numbers.extend(other.phone_numbers)
        self.emails.extend(other.emails)
        return self

    def is_duplicate_of(self, other: "Contact", name_order: str = "first_name_first") -> bool:
        """Check if this contact is a duplicate of another contact for merging purposes.
        A contact is considered identical when the name and either a (normalized)
        telephone number or an email address matches.
        """
        if self.name != other.name:
            return False

        self_normalized_identity = self.get_normalized_identity(name_order)
        other_normalized_identity = other.get_normalized_identity(name_order)

        return self_normalized_identity == other_normalized_identity

    def get_all_phone_numbers(self) -> List[str]:
        """Get all phone numbers from the contact."""
        return [phone.number for phone in self.phone_numbers]

    def get_all_email_addresses(self) -> List[str]:
        """Get all email addresses from the contact."""
        return [email.email for email in self.emails]

    def has_same_identity(self, other: "Contact") -> bool:
        """Check if two contacts have the same identity (name + primary phone/email)."""
        return (self.name == other.name and
                (self.get_primary_phone() and other.get_primary_phone() and
                 self.get_primary_phone().number == other.get_primary_phone().number) or
                (self.get_primary_email() and other.get_primary_email() and
                 self.get_primary_email().email == other.get_primary_email().email))
