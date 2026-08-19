"""Unit tests for the TR-064 phonebook client (X_AVM-DE_OnTel:1).

Covers phonebook listing, name resolution and creation used to honor the
configured ``target_book`` name (the main phonebook 0 cannot be renamed).
"""

import logging

import pytest

from src.services.tr064 import Tr064Client


def _client():
    logger = logging.getLogger("test_tr064")
    logger.addHandler(logging.NullHandler())
    return Tr064Client("fritz.box", "user", "pass", logger)


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def _fake_post_factory(body_fn):
    """Build a fake requests.post that dispatches on the SOAP action."""

    def fake_post(url, data, auth, headers, timeout):
        body = data if isinstance(data, str) else data.decode()
        if "GetPhonebookList" in body:
            return _FakeResponse(body_fn("GetPhonebookList"))
        if "GetPhonebook" in body:
            return _FakeResponse(body_fn("GetPhonebook"))
        if "AddPhonebook" in body:
            return _FakeResponse(body_fn("AddPhonebook"))
        raise AssertionError(f"Unexpected SOAP action in: {body}")

    return fake_post


def test_list_phonebooks_parses_indexes_names_and_real_ids(monkeypatch):
    """Indexes come from GetPhonebookList; names/real ids from GetPhonebook."""
    responses = {
        "GetPhonebookList": (
            "<s:Body><u:GetPhonebookListResponse>"
            "<NewPhonebookList>0,1</NewPhonebookList>"
            "</u:GetPhonebookListResponse></s:Body>"
        ),
        "GetPhonebook": (
            "<s:Body><u:GetPhonebookResponse>"
            "<NewPhonebookName>Telefoonboek</NewPhonebookName>"
            "<NewPhonebookURL>http://[::1]:49000/phonebook.lua?sid=x&amp;pbid=0"
            "</NewPhonebookURL></u:GetPhonebookResponse></s:Body>"
        ),
    }
    monkeypatch.setattr(
        "src.services.tr064.requests.post",
        _fake_post_factory(lambda action: responses[action]),
    )

    books = _client().list_phonebooks()

    assert books == [(0, "Telefoonboek", 0), (1, "Telefoonboek", 0)]


def test_phonebook_info_extracts_real_id_from_pbid(monkeypatch):
    """The firmwarecfg import id is the pbid in the NewPhonebookURL."""
    monkeypatch.setattr(
        "src.services.tr064.requests.post",
        _fake_post_factory(
            lambda action: (
                "<s:Body><u:GetPhonebookResponse>"
                "<NewPhonebookName>Test</NewPhonebookName>"
                "<NewPhonebookURL>http://[::1]:49000/phonebook.lua?sid=x&amp;pbid=2"
                "</NewPhonebookURL></u:GetPhonebookResponse></s:Body>"
            )
        ),
    )

    name, real_id = _client()._phonebook_info(1)

    assert name == "Test"
    assert real_id == 2


def test_list_phonebooks_empty_list_on_missing_element(monkeypatch):
    monkeypatch.setattr(
        "src.services.tr064.requests.post",
        _fake_post_factory(lambda action: "<s:Body></s:Body>"),
    )
    assert _client().list_phonebooks() == []


def test_resolve_phonebook_id_finds_existing(monkeypatch):
    """An existing book with the target name is returned without AddPhonebook."""
    responses = {
        "GetPhonebookList": ("<NewPhonebookList>0,1</NewPhonebookList>"),
        "GetPhonebook": (
            "<NewPhonebookName>Test</NewPhonebookName>"
            "<NewPhonebookURL>http://x?pbid=2</NewPhonebookURL>"
        ),
    }
    calls = []

    def fake_post(url, data, auth, headers, timeout):
        body = data if isinstance(data, str) else data.decode()
        calls.append(body)
        if "GetPhonebookList" in body:
            return _FakeResponse(responses["GetPhonebookList"])
        if "GetPhonebook" in body:
            return _FakeResponse(responses["GetPhonebook"])
        raise AssertionError(f"Unexpected action: {body}")

    monkeypatch.setattr("src.services.tr064.requests.post", fake_post)

    result = _client().resolve_phonebook_id("Test")

    assert result == 2
    assert not any("AddPhonebook" in c for c in calls)


def test_resolve_phonebook_id_creates_when_missing(monkeypatch):
    """A missing book is created via AddPhonebook and then resolved."""
    counter = {"add": 0}

    def fake_post(url, data, auth, headers, timeout):
        body = data if isinstance(data, str) else data.decode()
        if "AddPhonebook" in body:
            counter["add"] += 1
            return _FakeResponse("<s:Body></s:Body>")
        if "GetPhonebookList" in body:
            if counter["add"]:
                return _FakeResponse("<NewPhonebookList>0,1</NewPhonebookList>")
            return _FakeResponse("<NewPhonebookList>0</NewPhonebookList>")
        if "GetPhonebook" in body:
            index = int(body.split("<NewPhonebookID>")[1].split("</NewPhonebookID>")[0])
            if counter["add"] and index == 1:
                return _FakeResponse(
                    "<NewPhonebookName>Test</NewPhonebookName>"
                    "<NewPhonebookURL>http://x?pbid=3</NewPhonebookURL>"
                )
            return _FakeResponse(
                "<NewPhonebookName>Telefoonboek</NewPhonebookName>"
                "<NewPhonebookURL>http://x?pbid=0</NewPhonebookURL>"
            )
        raise AssertionError(f"Unexpected action: {body}")

    monkeypatch.setattr("src.services.tr064.requests.post", fake_post)

    result = _client().resolve_phonebook_id("Test")

    assert result == 3
    assert counter["add"] == 1


def test_resolve_phonebook_id_returns_none_on_add_failure(monkeypatch):
    """When AddPhonebook fails the resolver returns None."""

    def fake_post(url, data, auth, headers, timeout):
        body = data if isinstance(data, str) else data.decode()
        if "GetPhonebookList" in body:
            return _FakeResponse("<NewPhonebookList>0</NewPhonebookList>")
        if "GetPhonebook" in body:
            return _FakeResponse(
                "<NewPhonebookName>Telefoonboek</NewPhonebookName>"
                "<NewPhonebookURL>http://x?pbid=0</NewPhonebookURL>"
            )
        raise RuntimeError("AddPhonebook rejected")

    monkeypatch.setattr("src.services.tr064.requests.post", fake_post)

    assert _client().resolve_phonebook_id("Test") is None


def test_list_phonebooks_returns_empty_on_transport_error(monkeypatch):
    def raise_error(*args, **kwargs):
        raise ConnectionError("port closed")

    monkeypatch.setattr("src.services.tr064.requests.post", raise_error)

    assert _client().list_phonebooks() == []


def test_resolve_phonebook_id_none_on_transport_error(monkeypatch):
    def raise_error(*args, **kwargs):
        raise ConnectionError("port closed")

    monkeypatch.setattr("src.services.tr064.requests.post", raise_error)

    assert _client().resolve_phonebook_id("Test") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
