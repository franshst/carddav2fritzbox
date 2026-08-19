"""Unit tests for the Contact model identity and deduplication logic.

Covers the REDO of T009: identity/deduplication compares telephone numbers
in the canonical normalized form (spec.md FR-018) via PhoneNumber.canonical
(spec.md FR-005).
"""

import pytest

from src.models.contact import Contact, PhoneNumber, EmailAddress

REGIONAL_DE = dict(country_code="+49", area_code="30", international_access_code="00")


class TestPhoneNumberCanonical:
    """Test PhoneNumber.canonical (FR-005 canonical normalized form)."""

    def test_already_international_passthrough(self):
        assert PhoneNumber("+4930123456").canonical(**REGIONAL_DE) == "+4930123456"

    def test_international_access_code_replaced(self):
        assert PhoneNumber("004930123456").canonical(**REGIONAL_DE) == "+4930123456"

    def test_leading_zero_replaced_with_country_code(self):
        assert PhoneNumber("030123456").canonical(**REGIONAL_DE) == "+4930123456"

    def test_no_prefix_prepends_country_and_area_code(self):
        assert PhoneNumber("1234567").canonical(**REGIONAL_DE) == "+49301234567"

    def test_without_config_falls_back_to_sanitized(self):
        assert PhoneNumber("+1 (415) 555-2671").canonical() == "+14155552671"

    def test_sanitize_strips_non_numeric(self):
        assert PhoneNumber("  (030) 123-456 ").sanitize() == "030123456"


class TestContactIdentity:
    """Test Contact identity/dedup compares canonical forms (FR-018)."""

    def test_duplicate_recognized_across_equivalent_raw_forms(self):
        contact1 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+4930123456", type="home", prio=1)],
            emails=[EmailAddress(email="john@example.com", classifier="private")],
        )
        contact2 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="030123456", type="home", prio=1)],
            emails=[EmailAddress(email="j.doe@work.com", classifier="work")],
        )
        assert contact1.is_duplicate_of(contact2, **REGIONAL_DE) is True

    def test_duplicate_recognized_via_international_access_code(self):
        contact1 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+4930123456", type="home", prio=1)],
            emails=[],
        )
        contact2 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="004930123456", type="home", prio=1)],
            emails=[],
        )
        assert contact1.is_duplicate_of(contact2, **REGIONAL_DE) is True

    def test_not_duplicate_when_foreign_number_and_no_email(self):
        contact1 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+4930123456", type="home", prio=1)],
            emails=[],
        )
        contact2 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+442079460958", type="work", prio=1)],
            emails=[],
        )
        assert contact1.is_duplicate_of(contact2, **REGIONAL_DE) is False

    def test_not_duplicate_when_names_differ(self):
        contact1 = Contact(name="John Doe", phone_numbers=[], emails=[])
        contact2 = Contact(name="Jane Smith", phone_numbers=[], emails=[])
        assert contact1.is_duplicate_of(contact2, **REGIONAL_DE) is False

    def test_email_match_is_sufficient(self):
        contact1 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+15551234567", type="home", prio=1)],
            emails=[EmailAddress(email="john@example.com", classifier="private")],
        )
        contact2 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+442079460958", type="work", prio=1)],
            emails=[EmailAddress(email="John@Example.com", classifier="work")],
        )
        assert contact1.has_same_identity(contact2) is True

    def test_shared_non_primary_phone_matches(self):
        contact1 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+15551234567", type="home", prio=1)],
            emails=[],
        )
        contact2 = Contact(
            name="John Doe",
            phone_numbers=[
                PhoneNumber(number="+15551234567", type="home", prio=0),
                PhoneNumber(number="+442079460958", type="work", prio=1),
            ],
            emails=[],
        )
        assert contact1.has_same_identity(contact2) is True

    def test_identity_includes_canonical_primary_phone(self):
        contact1 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+4930123456", type="home", prio=1)],
            emails=[],
        )
        identity = contact1.get_normalized_identity(**REGIONAL_DE)
        assert "John Doe" in identity
        assert "+4930123456" in identity


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
