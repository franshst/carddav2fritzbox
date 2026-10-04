"""FTP-based contact picture upload for the FritzBox (FR-020).

The FritzBox stores contact pictures as files on its own storage (internal or
USB) and references them from the phonebook XML via ``file:///...`` URLs; it
does not resolve embedded data URIs. This module therefore uploads the
converted baseline-JPEG pictures into the box's ``fonpix`` directory over FTP
(plain or explicit FTPS) — the same mechanism the reference implementation
andig/carddav2fb uses — and returns the ``file:///`` URL to write into
``<imageURL>`` (research.md section 7, contracts/fritzbox-api.md).
"""

import ftplib
import hashlib
import io
import logging
import re
import time
from typing import Dict, List, Optional

from src.models.contact import Contact

# Files managed by this tool in the fonpix directory follow '<key>_<epoch>.jpg'.
# The underscore separator distinguishes them from the box's own files, which
# use a '<timestamp>-<index>.jpg' scheme, so orphan cleanup never touches files
# the box or other tools created.
_MANAGED_FILE_RE = re.compile(r"^([0-9a-zA-Z._-]+)_(\d{10})\.jpg$")


def _identity_digest(contact: Contact, length: int = 12) -> str:
    """Short SHA1 digest of a contact's identity (name + phones + emails)."""
    digest = hashlib.sha1()
    digest.update(contact.name.encode("utf-8", "replace"))
    for phone in sorted(p.number for p in contact.phone_numbers):
        digest.update(b"|" + phone.encode("utf-8", "replace"))
    for email in sorted(e.email.casefold() for e in contact.emails):
        digest.update(b"|" + email.encode("utf-8", "replace"))
    return digest.hexdigest()[:length]


def image_key(contact: Contact) -> str:
    """Return a stable per-contact key used to name its image file.

    Combines the numeric vCard UID (when present) with a short digest of
    the contact's identity (name + phones + emails). The UID alone is not
    unique: it is only the first digit-run of the vCard UID, so distinct
    contacts (e.g. UUID-style UIDs starting with the same digit) would
    otherwise share one image file and one ``<imageURL>`` (FR-020). The
    digest keeps the key stable across sync runs even when the UID is
    missing or collides.
    """
    if contact.unique_id is not None:
        return f"{contact.unique_id}-{_identity_digest(contact, 8)}"
    return _identity_digest(contact)


class FritzBoxImageUploader:
    """Uploads contact JPEGs into the FritzBox ``fonpix`` directory over FTP.

    Args:
        host: FTP host (usually the FritzBox itself).
        username: FTP/NAS username.
        password: FTP/NAS password.
        fonpix_dir: Directory on the box where contact images are stored
            (e.g. ``/FRITZ/fonpix`` on internal storage, or the equivalent
            path on a USB stick).
        imagepath: ``file:///`` URL prefix mapping ``fonpix_dir`` to the box
            (e.g. ``file:///var/InternerSpeicher/FRITZ/fonpix``).
        plain: Use plain FTP (default) instead of explicit FTPS.
        logger: Logger for diagnostics.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        fonpix_dir: str,
        imagepath: str,
        plain: bool = True,
        logger: Optional[logging.Logger] = None,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.fonpix_dir = fonpix_dir.strip("/")
        self.imagepath = imagepath.rstrip("/")
        self.plain = plain
        self.logger = logger or logging.getLogger(__name__)

    def sync_images(self, contacts: List[Contact]) -> Dict[str, str]:
        """Upload pictures for ``contacts`` and return ``{key: imageURL}``.

        Existing managed files whose size matches the current picture are
        reused; stale managed files for the same contact are removed and
        orphaned files (keys no longer present in ``contacts``) are deleted.
        Any failure is logged and the affected picture is simply omitted.

        Callers must run :meth:`check_directory` first and abort the sync when
        it reports the FTP picture directory is unavailable (spec.md FR-021).

        Args:
            contacts: Contacts to sync pictures for.

        Returns:
            Mapping of contact key to the ``file:///`` URL to write into
            ``<imageURL>``. Contacts without a picture are not included.
        """
        by_key: Dict[str, Contact] = {}
        for contact in contacts:
            if not contact.picture_data:
                continue
            key = image_key(contact)
            if key in by_key:
                self.logger.warning(
                    f"Duplicate image key {key} for '{by_key[key].name}' and "
                    f"'{contact.name}'; keeping the first picture"
                )
                continue
            by_key[key] = contact

        try:
            ftp = self._connect()
        except ftplib.all_errors as e:
            self.logger.error(f"FTP connection to {self.host} failed: {e}")
            return {}

        try:
            existing = self._list_managed(ftp)
            urls: Dict[str, str] = {}
            for key, contact in by_key.items():
                self.logger.debug(
                    f"Picture for '{contact.name}' (key {key}): "
                    f"{len(contact.picture_data or b'')} bytes, "
                    f"existing files {existing.get(key, [])}"
                )
                url = self._upload_contact(ftp, key, contact, existing.get(key, []))
                if url is not None:
                    urls[key] = url

            wanted = set(by_key)
            for key, filenames in existing.items():
                if key not in wanted:
                    for filename in filenames:
                        self._delete(ftp, filename)
            return urls
        except ftplib.all_errors as e:
            self.logger.error(f"FTP picture sync failed: {e}")
            return {}
        finally:
            try:
                ftp.quit()
            except ftplib.all_errors:
                pass

    def check_directory(self) -> bool:
        """Verify the FTP picture directory is available before any upload.

        Connects and ensures ``fonpix_dir`` exists on the box (creating it
        when the FTP user may). Returns ``False`` when the directory cannot be
        reached or created; the caller must then abort the sync so the existing
        phonebook is left untouched (spec.md FR-021).

        Returns:
            True when the picture directory is available, False otherwise
            (a clear error is logged).
        """
        ftp = None
        try:
            ftp = self._connect()
        except ftplib.all_errors as e:
            self.logger.error(
                f"FTP picture directory '{self.fonpix_dir}' is not available "
                f"on {self.host}: {e}"
            )
            return False
        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except ftplib.all_errors:
                    pass
        return True

    def _connect(self) -> ftplib.FTP:
        """Open an FTP connection and change into the fonpix directory."""
        ftp = (
            ftplib.FTP(self.host, timeout=10)
            if self.plain
            else ftplib.FTP_TLS(self.host, timeout=10)
        )
        ftp.login(self.username, self.password)
        if not self.plain:
            ftp.prot_p()
        ftp.set_pasv(True)
        if self.fonpix_dir:
            try:
                ftp.cwd(self.fonpix_dir)
            except ftplib.all_errors:
                self._mkdirs(ftp, self.fonpix_dir)
                ftp.cwd(self.fonpix_dir)
        return ftp

    @staticmethod
    def _mkdirs(ftp: ftplib.FTP, path: str) -> None:
        """Create ``path`` (and parents) on the FTP server.

        ``MKD`` failures for existing directories are ignored.
        """
        current = ""
        for part in path.split("/"):
            if not part:
                continue
            current = f"{current}/{part}"
            try:
                ftp.mkd(current)
            except ftplib.all_errors:
                pass

    def _list_managed(self, ftp: ftplib.FTP) -> Dict[str, List[str]]:
        """Group the files managed by this tool in the fonpix dir by key."""
        try:
            names = ftp.nlst()
        except ftplib.all_errors:
            return {}
        grouped: Dict[str, List[str]] = {}
        for name in names:
            match = _MANAGED_FILE_RE.match(name)
            if match:
                grouped.setdefault(match.group(1), []).append(name)
        return grouped

    def _upload_contact(
        self,
        ftp: ftplib.FTP,
        key: str,
        contact: Contact,
        existing: List[str],
    ) -> Optional[str]:
        """Upload one contact's picture, returning its ``file:///`` URL.

        An existing managed file whose size equals the current picture is
        reused (avoids re-uploading unchanged images). Otherwise a new
        ``<key>_<epoch>.jpg`` file is stored and the stale files for the same
        key are removed.
        """
        data = contact.picture_data or b""
        for filename in existing:
            try:
                if ftp.size(filename) == len(data):
                    self.logger.debug(
                        f"Picture for '{contact.name}' (key {key}): reusing "
                        f"existing file {filename} ({len(data)} bytes)"
                    )
                    return f"{self.imagepath}/{filename}"
            except ftplib.all_errors:
                continue

        filename = f"{key}_{int(time.time())}.jpg"
        try:
            ftp.storbinary(f"STOR {filename}", io.BytesIO(data))
        except ftplib.all_errors as e:
            self.logger.warning(f"Failed to upload picture for {contact.name}: {e}")
            return None

        for old in existing:
            self._delete(ftp, old)
        self.logger.info(
            f"Uploaded contact picture for '{contact.name}' (key {key}): "
            f"{filename} ({len(data)} bytes)"
        )
        return f"{self.imagepath}/{filename}"

    def _delete(self, ftp: ftplib.FTP, filename: str) -> None:
        """Remove a managed file, logging but not failing on errors."""
        try:
            ftp.delete(filename)
        except ftplib.all_errors as e:
            self.logger.warning(f"Could not remove stale image {filename}: {e}")
