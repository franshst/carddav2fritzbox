"""TR-064 SOAP client for FritzBox phonebook management.

The X_AVM-DE_OnTel:1 TR-064 service (port 49000) exposes the phonebook
management actions used to resolve and create phonebooks by name
(research.md section 3.3):

- ``GetPhonebookList``: comma-separated list of phonebook indexes
- ``GetPhonebook(NewPhonebookID=<index>)``: name, extra id and URL of the
  book; the URL carries the *real* phonebook id (``pbid``) used by the
  firmwarecfg import
- ``AddPhonebook(NewPhonebookExtraID, NewPhonebookName)``: creates a
  phonebook with the given name (error 820 when the name already exists)
- ``DeletePhonebook(NewPhonebookID=<index>, NewPhonebookExtraID)``: deletes
  the book at the given *index* (not the real id)

Authentication uses HTTP Digest auth with the FRITZ!Box credentials.
"""

import logging
import re
from typing import List, Optional, Tuple

import requests
from requests.auth import HTTPDigestAuth

TR064_PORT = 49000
ONTEL_SERVICE = "urn:dslforum-org:service:X_AVM-DE_OnTel:1"
ONTEL_CONTROL = "/upnp/control/x_contact"


class Tr064Client:
    """Minimal TR-064 X_AVM-DE_OnTel:1 client for phonebook management.

    Args:
        host: FritzBox hostname or IP (without scheme/port)
        username: FRITZ!Box username
        password: FRITZ!Box password
        logger: Optional logger instance
        port: TR-064 port (default 49000)
        timeout: Request timeout in seconds
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        logger: Optional[logging.Logger] = None,
        port: int = TR064_PORT,
        timeout: int = 10,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self.logger = logger or logging.getLogger(__name__)

    def _soap(self, action: str, arguments: Optional[dict] = None) -> str:
        """Perform a SOAP call against the X_AVM-DE_OnTel:1 service.

        Args:
            action: SOAP action name (e.g. ``GetPhonebookList``)
            arguments: In-arguments for the action

        Returns:
            Response body as text

        Raises:
            requests.RequestException: On transport/HTTP errors
        """
        args = "".join(f"<{k}>{v}</{k}>" for k, v in (arguments or {}).items())
        body = (
            '<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            f'<s:Body><u:{action} xmlns:u="{ONTEL_SERVICE}">{args}'
            f"</u:{action}></s:Body></s:Envelope>"
        )
        url = f"http://{self.host}:{self.port}{ONTEL_CONTROL}"
        response = requests.post(
            url,
            data=body,
            auth=HTTPDigestAuth(self.username, self.password),
            headers={
                "SOAPACTION": f'"{ONTEL_SERVICE}#{action}"',
                "Content-Type": "text/xml; charset=utf-8",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.text

    def list_phonebooks(self) -> List[Tuple[int, str, int]]:
        """Return ``(index, name, real_id)`` for every phonebook on the device.

        Returns:
            List of phonebooks; an empty list on failure.
        """
        try:
            text = self._soap("GetPhonebookList")
        except Exception as e:
            self.logger.warning(f"TR-064 GetPhonebookList failed: {e}")
            return []

        match = re.search(r"<NewPhonebookList>([^<]*)</NewPhonebookList>", text)
        if not match:
            return []

        books = []
        for raw_index in match.group(1).split(","):
            raw_index = raw_index.strip()
            if not raw_index:
                continue
            try:
                name, real_id = self._phonebook_info(int(raw_index))
            except Exception as e:
                self.logger.warning(
                    f"TR-064 GetPhonebook failed for index {raw_index}: {e}"
                )
                continue
            books.append((int(raw_index), name, real_id))
        return books

    def _phonebook_info(self, index: int) -> Tuple[str, int]:
        """Return ``(name, real_id)`` for the phonebook at the given index.

        The *real* phonebook id used by the firmwarecfg import is parsed from
        the ``pbid`` query parameter of the ``NewPhonebookURL``.
        """
        text = self._soap("GetPhonebook", {"NewPhonebookID": index})
        name_match = re.search(r"<NewPhonebookName>([^<]*)</NewPhonebookName>", text)
        url_match = re.search(r"<NewPhonebookURL>([^<]*)</NewPhonebookURL>", text)

        name = name_match.group(1) if name_match else ""
        real_id = index
        if url_match:
            pbid = re.search(r"pbid=(\d+)", url_match.group(1))
            if pbid:
                real_id = int(pbid.group(1))
        return name, real_id

    def add_phonebook(self, name: str) -> None:
        """Create a phonebook with the given name.

        Args:
            name: Name for the new phonebook

        Raises:
            requests.RequestException: On failure (e.g. duplicate name, 820)
        """
        self._soap(
            "AddPhonebook", {"NewPhonebookExtraID": "", "NewPhonebookName": name}
        )

    def resolve_phonebook_id(self, target_name: str) -> Optional[int]:
        """Return the real phonebook id whose name matches ``target_name``.

        When no book with that name exists, it is created via
        ``AddPhonebook``. Returns ``None`` when the target cannot be resolved
        (e.g. TR-064 is unreachable or the name is rejected).
        """
        for _index, name, real_id in self.list_phonebooks():
            if name == target_name:
                return real_id

        try:
            self.add_phonebook(target_name)
        except Exception as e:
            self.logger.warning(f"TR-064 AddPhonebook({target_name!r}) failed: {e}")
            return None

        for _index, name, real_id in self.list_phonebooks():
            if name == target_name:
                return real_id
        return None
