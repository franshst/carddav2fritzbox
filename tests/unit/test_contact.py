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

    def test_bare_number_without_prefix_gets_country_and_area(self):
        """A bare number with no '+' / international access code / trunk '0'
        is treated as a local number: country code + area code are prepended
        (FR-005). Numbers are matched on the leading '+' only."""
        assert (
            PhoneNumber("31612345678").canonical(
                country_code="+31", area_code="20", international_access_code="00"
            )
            == "+312031612345678"
        )

    def test_bare_number_with_country_prefix_gets_area_prepend(self):
        """A bare number starting with the country-code digits (and no '+')
        is NOT recognised as E.164 without '+'; country + area are prepended
        (FR-005). The '+' is the only international marker."""
        assert (
            PhoneNumber("31703141414").canonical(
                country_code="+31", area_code="20", international_access_code="00"
            )
            == "+312031703141414"
        )

    def test_bare_number_short_remainder_falls_back(self):
        """A short bare remainder after the country-code digits is also treated
        as local (country + area prepended), never as international-without-'+'."""
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

    # --- FR-004 fill-in rule for single-occurrence fields ---

    def test_picture_filled_from_lower_priority(self):
        """A higher-priority contact without a picture adopts the picture from
        the lower-priority source (fill-in rule, FR-004/FR-020)."""
        high = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+4930123456")],
            picture_data=None,
            picture_url=None,
        )
        low = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+4930123456")],
            picture_data=b"jpg-bytes",
            picture_url=None,
        )
        merged = high.merge_with(low, **REGIONAL_DE)
        assert merged.picture_data == b"jpg-bytes"

    def test_picture_kept_from_higher_priority(self):
        """A higher-priority picture is never replaced by a lower-priority one."""
        high = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+4930123456")],
            picture_data=b"high",
            picture_url=None,
        )
        low = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber(number="+4930123456")],
            picture_data=b"low",
            picture_url=None,
        )
        merged = high.merge_with(low, **REGIONAL_DE)
        assert merged.picture_data == b"high"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
