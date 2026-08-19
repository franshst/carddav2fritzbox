"""Unit tests for the Contact model identity and deduplication logic.

Covers the REDO of T009: identity/deduplication compares telephone numbers
in the canonical normalized form (spec.md FR-018) via PhoneNumber.canonical
(spec.md FR-005).
"""

import pytest

from src.models.contact import Contact, EmailAddress, PhoneNumber

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

    def test_country_code_without_plus_prepends_plus(self):
        """E.164 without '+' is recognized and gets a '+' prefix only."""
        assert (
            PhoneNumber("31703141414").canonical(
                country_code="+31", area_code="20", international_access_code="00"
            )
            == "+31703141414"
        )

    def test_country_code_without_plus_mobile(self):
        """A mobile E.164 without '+' keeps the full number (FR-005)."""
        assert (
            PhoneNumber("31612345678").canonical(
                country_code="+31", area_code="20", international_access_code="00"
            )
            == "+31612345678"
        )

    def test_country_code_without_plus_short_remainder_falls_back(self):
        """A short remainder after the country digits is not treated as E.164."""
        assert (
            PhoneNumber("317031").canonical(
                country_code="+31", area_code="20", international_access_code="00"
            )
            == "+3120317031"
        )


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


class TestMergeWithDedup:
    """Multi-value fields are appended only when unique (FR-004)."""

    def test_identical_canonical_phone_appended_once(self):
        """Raw forms that share a canonical form (FR-018) collapse to one; the
        first occurrence wins and keeps its original raw representation."""
        contact1 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+4930123456", type="home", prio=1)],
            emails=[],
        )
        contact2 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="030123456", type="home", prio=1)],
            emails=[],
        )
        merged = contact1.merge_with(contact2, **REGIONAL_DE)
        assert len(merged.phone_numbers) == 1
        assert merged.phone_numbers[0].number == "+4930123456"

    def test_case_variant_email_appended_once(self):
        """Email addresses differing only in case collapse to one."""
        contact1 = Contact(
            name="John Doe",
            phone_numbers=[],
            emails=[EmailAddress(email="John@Example.com", classifier="private")],
        )
        contact2 = Contact(
            name="John Doe",
            phone_numbers=[],
            emails=[EmailAddress(email="john@example.com", classifier="work")],
        )
        merged = contact1.merge_with(contact2)
        assert len(merged.emails) == 1
        assert merged.emails[0].email == "John@Example.com"

    def test_distinct_values_are_preserved(self):
        """Genuinely distinct phones and emails are all appended."""
        contact1 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+4930123456", type="home", prio=1)],
            emails=[EmailAddress(email="john@example.com", classifier="private")],
        )
        contact2 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+14155552671", type="mobile", prio=1)],
            emails=[EmailAddress(email="john@work.com", classifier="work")],
        )
        merged = contact1.merge_with(contact2, **REGIONAL_DE)
        assert len(merged.phone_numbers) == 2
        assert len(merged.emails) == 2

    def test_without_config_dedups_exact_strings(self):
        """Without regional config, phone comparison falls back to the
        sanitized exact form; identical strings are still deduplicated."""
        contact1 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+4930123456")],
            emails=[EmailAddress(email="john@example.com")],
        )
        contact2 = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+4930123456")],
            emails=[EmailAddress(email="john@example.com")],
        )
        merged = contact1.merge_with(contact2)
        assert len(merged.phone_numbers) == 1
        assert len(merged.emails) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
