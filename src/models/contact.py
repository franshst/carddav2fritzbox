"""Contact intermediate model representations."""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple


def canonicalize_phone(
    digits: str,
    country_code: str = "",
    area_code: str = "",
    international_access_code: str = "",
) -> str:
    """Return the canonical normalized form of a phone number (spec.md FR-005).

    Canonical form contains only digits and a leading '+' (international
    access sign). Algorithm:
    1. If the number starts with '+', it is already canonical.
    2. If it starts with the numeric international access code from config
       (e.g. ``00`` Europe, ``09`` US), replace that code with '+'.
    3. If it starts with '0', replace the leading '0' with '+' + country code.
    4. If it already carries the country code without '+' (E.164 form, e.g.
       ``31703141414``), prepend '+' only when the remainder is 8-12 digits.
    5. Otherwise prepend '+' + country code + area code (without leading zero).

    ``digits`` is expected to be sanitized first (only digits and an optional
    leading '+' - FR-014). Without regional config, falls back to the input as
    returned (numbers are assumed to be in canonical form).
    """
    if not digits or digits.startswith("+"):
        return digits

    country_digits = re.sub(r"[^0-9]", "", country_code)
    if not country_digits:
        return digits

    access_digits = re.sub(r"[^0-9]", "", international_access_code)
    if access_digits and digits.startswith(access_digits):
        return "+" + digits[len(access_digits) :]

    if digits.startswith("0"):
        return "+" + country_digits + digits[1:]

    # The number already carries the country code without the '+' (E.164 form
    # without the international prefix). When the remainder has the length of a
    # national number, prepend '+' only.
    if digits.startswith(country_digits):
        remainder = digits[len(country_digits) :]
        if 8 <= len(remainder) <= 12:
            return "+" + digits

    area_digits = re.sub(r"[^0-9]", "", area_code).lstrip("0")
    return "+" + country_digits + area_digits + digits


@dataclass
class PhoneNumber:
    number: str
    type: str = "home"  # "home", "mobile", "work", "fax"
    prio: int = 0  # 1 for primary number, 0 for secondary numbers
    quickdial: str = ""
    vanity: str = ""

    def normalize(self) -> "PhoneNumber":
        """Normalize phone number by stripping non-numeric characters except
        a leading '+'.
        """
        self.number = re.sub(r"[^0-9+]", "", self.number)
        return self

    def sanitize(self) -> str:
        """Sanitize a phone number: keep only digits and an optional leading '+'."""
        return re.sub(r"[^0-9+]", "", self.number)

    def canonical(
        self,
        country_code: str = "",
        area_code: str = "",
        international_access_code: str = "",
    ) -> str:
        """Return the canonical normalized form of this number (spec.md FR-005).

        Canonical form contains only digits and a leading '+' (international
        access sign). See :func:`canonicalize_phone` for the algorithm.

        Without regional config, falls back to the sanitized form (numbers are
        assumed to be stored in canonical form). Comparison of phone numbers for
        identity/deduplication always uses this form (spec.md FR-018).
        """
        return canonicalize_phone(
            self.sanitize(), country_code, area_code, international_access_code
        )

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
        return re.sub(r"[^0-9+]", "", phone)


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
        """Get the primary phone number (prio=1), or the first phone if none
        is marked as primary.
        """
        for phone in self.phone_numbers:
            if phone.is_primary():
                return phone
        return self.phone_numbers[0] if self.phone_numbers else None

    def get_primary_email(self) -> Optional[EmailAddress]:
        """Get the primary email address (classifier="private"), or the first
        email if none is marked as primary.
        """
        for email in self.emails:
            if email.is_primary():
                return email
        return self.emails[0] if self.emails else None

    def get_normalized_identity(
        self,
        name_order: str = "first_name_first",
        country_code: str = "",
        area_code: str = "",
        international_access_code: str = "",
    ) -> str:
        """Get contact identity string for merging: formatted name plus the
        primary phone or email.

        The phone number is compared in its canonical normalized form (FR-018).
        """
        formatted_name = self._format_name(name_order)
        identity_parts = [formatted_name]

        primary_phone = self.get_primary_phone()
        if primary_phone:
            identity_parts.append(
                primary_phone.canonical(
                    country_code, area_code, international_access_code
                )
            )
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

    def is_duplicate_of(
        self,
        other: "Contact",
        name_order: str = "first_name_first",
        country_code: str = "",
        area_code: str = "",
        international_access_code: str = "",
    ) -> bool:
        """Check if this contact is a duplicate of another contact for merging.

        Per spec.md FR-004 and FR-018, a contact is identical when the name
        matches AND either a canonical telephone number or an email address
        matches.
        """
        return self.has_same_identity(
            other, country_code, area_code, international_access_code
        )

    def get_all_phone_numbers(self) -> List[str]:
        """Get all phone numbers from the contact."""
        return [phone.number for phone in self.phone_numbers]

    def get_all_email_addresses(self) -> List[str]:
        """Get all email addresses from the contact."""
        return [email.email for email in self.emails]

    def has_same_identity(
        self,
        other: "Contact",
        country_code: str = "",
        area_code: str = "",
        international_access_code: str = "",
    ) -> bool:
        """Check if two contacts have the same identity.

        True when the names match AND either any canonical telephone number is
        shared (FR-018) or any email address is shared (FR-004).
        """
        if self.name != other.name:
            return False

        self_phones = self._canonical_phone_set(
            country_code, area_code, international_access_code
        )
        other_phones = other._canonical_phone_set(
            country_code, area_code, international_access_code
        )
        if self_phones & other_phones:
            return True

        self_emails = {email.email.casefold() for email in self.emails}
        other_emails = {email.email.casefold() for email in other.emails}
        return bool(self_emails & other_emails)

    def _canonical_phone_set(
        self, country_code: str, area_code: str, international_access_code: str
    ) -> Set[str]:
        """Set of this contact's phone numbers in canonical normalized form (FR-018)."""
        return {
            phone.canonical(country_code, area_code, international_access_code)
            for phone in self.phone_numbers
            if phone.number
        }
