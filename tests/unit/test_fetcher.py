"""Unit tests for the CardDAV fetcher's parsing and merge logic."""

import logging

import vobject

from src.config.loader import (
    SyncConfig,
    GeneralConfig,
    FritzBoxConfig,
    RegionalConfig,
    CardDAVSourceConfig,
)
from src.models.contact import Contact, PhoneNumber, EmailAddress
from src.services.carddav_fetcher import CardDAVFetcher


def _make_config() -> SyncConfig:
    return SyncConfig(
        general=GeneralConfig(name_order="first_name_first"),
        fritzbox=FritzBoxConfig(url="http://fritz.box", username="u", password="p"),
        regional=RegionalConfig(
            country="NL",
            region="Amsterdam",
            country_code="+31",
            area_code="20",
            international_access_code="00",
        ),
        sources=[
            CardDAVSourceConfig(
                url="https://dav/prio1", username="u", password="p", priority=1
            ),
            CardDAVSourceConfig(
                url="https://dav/prio2", username="u", password="p", priority=2
            ),
        ],
    )


def _make_fetcher() -> CardDAVFetcher:
    logger = logging.getLogger("test_fetcher")
    logger.addHandler(logging.NullHandler())
    return CardDAVFetcher(_make_config(), logger)


class TestSplitVcards:
    def test_preserves_line_folding(self):
        """Folded vCard lines (RFC 6350 §3.2) must survive the split so vobject
        can unfold them; a folded photo must not make the card unparseable."""
        card = (
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            "FN:Aart Stuurman\r\n"
            "N:Stuurman;Aart;;;\r\n"
            "TEL;TYPE=cell:0640278235\r\n"
            "PHOTO;ENCODING=b;TYPE=JPEG:QUJD\r\n"
            " RA==\r\n"
            "END:VCARD\r\n"
        )
        fetcher = _make_fetcher()
        cards = fetcher._split_vcards(card)
        assert len(cards) == 1
        parsed = vobject.readOne(cards[0])
        assert parsed.fn.value == "Aart Stuurman"
        assert parsed.photo.value == b"ABCD"

    def test_split_multiple_cards(self):
        """A body with several concatenated vCards yields one entry per card."""
        fetcher = _make_fetcher()
        body = (
            "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:One\r\nEND:VCARD\r\n"
            "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Two\r\nEND:VCARD\r\n"
        )
        cards = fetcher._split_vcards(body)
        assert len(cards) == 2

    def test_unclosed_block_is_kept(self):
        """A trailing block without END:VCARD is attempted anyway."""
        fetcher = _make_fetcher()
        cards = fetcher._split_vcards("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Orphan")
        assert len(cards) == 1


class TestMergeContacts:
    def test_merges_duplicate_across_sources(self):
        """A contact present in both sources collapses into one entry and the
        first (highest priority) one wins, appending multi-value fields."""
        fetcher = _make_fetcher()
        prio1 = Contact(
            name="Aart Stuurman",
            phone_numbers=[PhoneNumber("06 40278235", type="home")],
            emails=[EmailAddress("aart@hotmail.com")],
        )
        prio2 = Contact(
            name="Aart Stuurman",
            phone_numbers=[PhoneNumber("0640278235", type="cell")],
            emails=[EmailAddress("aartstuurman@hotmail.com")],
        )
        merged = fetcher.merge_contacts([prio1, prio2])
        assert len(merged) == 1
        assert len(merged[0].phone_numbers) == 2
        assert len(merged[0].emails) == 2

    def test_keeps_distinct_contacts(self):
        """Contacts with different identities stay separate."""
        fetcher = _make_fetcher()
        a = Contact(name="Aart Stuurman", phone_numbers=[PhoneNumber("0640278235")])
        b = Contact(name="Jan Jansen", phone_numbers=[PhoneNumber("0612345678")])
        merged = fetcher.merge_contacts([a, b])
        assert len(merged) == 2
