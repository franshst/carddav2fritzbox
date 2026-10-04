"""Unit tests for the FTP-based contact picture uploader (FR-020).

Tests src/services/fritzbox_images.py:
- Stable per-contact image keys (image_key)
- FTP upload, size-based reuse, stale-file and orphan cleanup
- Plain FTP vs explicit FTPS selection
- Graceful failure handling (connection/upload errors omit the picture)
"""

from src.models.contact import Contact, EmailAddress, PhoneNumber
from src.services.fritzbox_images import FritzBoxImageUploader, image_key

_IMAGEPATH = "file:///var/InternerSpeicher/FRITZ/fonpix"


class _FakeFTP:
    """In-memory stand-in for ftplib.FTP covering the used surface."""

    def __init__(self):
        self.files = {}
        self.stored = []
        self.deleted = []
        self.mkdirs = []
        self.cwd_attempts = []
        self.cwd_fail = False
        self.prot_p_called = False
        self.quit_called = False
        self.fail_storbinary = False
        self.used_tls = False

    def login(self, username, password):
        self.login_args = (username, password)

    def set_pasv(self, value):
        self.pasv = value

    def cwd(self, path):
        self.cwd_attempts.append(path)
        if self.cwd_fail:
            raise OSError("550 No such directory")

    def mkd(self, path):
        self.mkdirs.append(path)

    def nlst(self):
        return list(self.files)

    def size(self, name):
        return len(self.files[name])

    def storbinary(self, cmd, fp):
        name = cmd.split(" ", 1)[1]
        self.files[name] = fp.read()
        self.stored.append(name)
        if self.fail_storbinary:
            raise OSError("550 Permission denied")

    def delete(self, name):
        self.files.pop(name, None)
        self.deleted.append(name)

    def prot_p(self):
        self.prot_p_called = True

    def quit(self):
        self.quit_called = True


def _patch_ftplib(monkeypatch, fake):
    """Replace ftplib.FTP/FTP_TLS with factories returning the fake."""

    def plain_factory(*args, **kwargs):
        fake.used_tls = False
        return fake

    def tls_factory(*args, **kwargs):
        fake.used_tls = True
        return fake

    monkeypatch.setattr("src.services.fritzbox_images.ftplib.FTP", plain_factory)
    monkeypatch.setattr("src.services.fritzbox_images.ftplib.FTP_TLS", tls_factory)


def _uploader(plain=True, fonpix_dir="/FRITZ/fonpix", **kwargs):
    return FritzBoxImageUploader(
        host="fritz.box",
        username="user",
        password="pass",
        fonpix_dir=fonpix_dir,
        imagepath=_IMAGEPATH,
        plain=plain,
        **kwargs,
    )


def _contact(key, picture_data=b"\xff\xd8fakejpeg"):
    return Contact(
        name=f"Contact {key}",
        phone_numbers=[PhoneNumber("030123456")],
        picture_data=picture_data,
        unique_id=key,
    )


class TestImageKey:
    """The image key must be stable and unique per contact."""

    def test_uses_unique_id_when_present(self):
        key = image_key(_contact(5))
        assert key.startswith("5-")
        assert key == image_key(_contact(5))

    def test_same_unique_id_differs_for_different_contacts(self):
        a = _contact(5, picture_data=b"\xff\xd8picture-a")
        b = Contact(
            name="Jane Doe",
            phone_numbers=[PhoneNumber("030999999")],
            picture_data=b"\xff\xd8picture-b",
            unique_id=5,
        )
        assert image_key(a) != image_key(b)

    def test_hash_key_is_stable_without_unique_id(self):
        contact = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber("+4930123456")],
            emails=[EmailAddress("john@example.com")],
        )
        assert image_key(contact) == image_key(contact)

    def test_hash_key_differs_for_different_contacts(self):
        a = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber("+4930123456")],
        )
        b = Contact(
            name="John Doe",
            phone_numbers=[PhoneNumber("+4930999999")],
        )
        assert image_key(a) != image_key(b)


class TestSyncImages:
    """FTP upload, reuse, and cleanup behaviour."""

    def test_uploads_new_file_and_returns_file_url(self, monkeypatch):
        fake = _FakeFTP()
        _patch_ftplib(monkeypatch, fake)
        uploader = _uploader()

        contact = _contact(5)
        key = image_key(contact)
        urls = uploader.sync_images([contact])

        assert len(fake.stored) == 1
        assert fake.stored[0].startswith(f"{key}_")
        assert fake.stored[0].endswith(".jpg")
        assert urls == {key: f"{_IMAGEPATH}/{fake.stored[0]}"}
        assert fake.pasv is True
        assert fake.quit_called is True

    def test_reuses_existing_file_with_matching_size(self, monkeypatch):
        contact = _contact(5)
        key = image_key(contact)
        fake = _FakeFTP()
        fake.files[f"{key}_1700000000.jpg"] = b"\xff\xd8fakejpeg"
        _patch_ftplib(monkeypatch, fake)
        uploader = _uploader()

        urls = uploader.sync_images([contact])

        assert fake.stored == []
        assert urls == {key: f"{_IMAGEPATH}/{key}_1700000000.jpg"}

    def test_removes_stale_files_for_same_key(self, monkeypatch):
        contact = _contact(5)
        key = image_key(contact)
        fake = _FakeFTP()
        fake.files[f"{key}_1700000000.jpg"] = b"stale-stale-stale-bytes"
        fake.files[f"{key}_1700000001.jpg"] = b"another-stale-bytes"
        _patch_ftplib(monkeypatch, fake)
        uploader = _uploader()

        urls = uploader.sync_images([contact])

        assert len(fake.stored) == 1
        assert fake.stored[0].startswith(f"{key}_")
        assert f"{key}_1700000000.jpg" in fake.deleted
        assert f"{key}_1700000001.jpg" in fake.deleted
        assert len(urls) == 1

    def test_same_unique_id_gets_separate_pictures(self, monkeypatch):
        """Regression test: two contacts sharing a numeric UID (first
        digit-run of UUID-style UIDs) must not share one image file."""
        fake = _FakeFTP()
        _patch_ftplib(monkeypatch, fake)
        uploader = _uploader()

        a = _contact(2, picture_data=b"\xff\xd8picture-a")
        b = Contact(
            name="Jane Doe",
            phone_numbers=[PhoneNumber("030999999")],
            picture_data=b"\xff\xd8picture-b",
            unique_id=2,
        )
        urls = uploader.sync_images([a, b])

        assert len(urls) == 2
        assert len(fake.stored) == 2
        assert urls[image_key(a)] != urls[image_key(b)]

    def test_deletes_orphaned_managed_files(self, monkeypatch):
        contact = _contact(5)
        key = image_key(contact)
        other = _contact(6)
        other_key = image_key(other)
        fake = _FakeFTP()
        fake.files[f"{key}_1700000000.jpg"] = b"\xff\xd8fakejpeg"
        fake.files[f"{other_key}_1700000000.jpg"] = b"y"
        fake.files["box-owned-1700000000-0.jpg"] = b"z"
        _patch_ftplib(monkeypatch, fake)
        uploader = _uploader()

        uploader.sync_images([contact])

        assert f"{other_key}_1700000000.jpg" in fake.deleted
        assert f"{key}_1700000000.jpg" not in fake.deleted
        assert fake.stored == []
        # Files not created by this tool are never touched.
        assert "box-owned-1700000000-0.jpg" not in fake.deleted

    def test_connection_failure_returns_empty(self, monkeypatch):
        def raise_error(*args, **kwargs):
            raise OSError("connection refused")

        monkeypatch.setattr("src.services.fritzbox_images.ftplib.FTP", raise_error)
        uploader = _uploader()

        assert uploader.sync_images([_contact(5)]) == {}

    def test_upload_failure_omits_only_that_picture(self, monkeypatch):
        fake = _FakeFTP()
        fake.fail_storbinary = True
        _patch_ftplib(monkeypatch, fake)
        uploader = _uploader()

        urls = uploader.sync_images([_contact(5)])

        assert urls == {}

    def test_creates_fonpix_directory_when_missing(self, monkeypatch):
        fake = _FakeFTP()
        fake.cwd_fail = True
        _patch_ftplib(monkeypatch, fake)
        uploader = _uploader()

        uploader.sync_images([_contact(5)])

        assert "/FRITZ" in fake.mkdirs
        assert "/FRITZ/fonpix" in fake.mkdirs


class TestCheckDirectory:
    """Pre-flight directory availability check (FR-021)."""

    def test_returns_true_when_directory_available(self, monkeypatch):
        fake = _FakeFTP()
        _patch_ftplib(monkeypatch, fake)
        uploader = _uploader()

        assert uploader.check_directory() is True
        assert fake.quit_called is True

    def test_returns_false_when_connection_fails(self, monkeypatch):
        def raise_error(*args, **kwargs):
            raise OSError("connection refused")

        monkeypatch.setattr("src.services.fritzbox_images.ftplib.FTP", raise_error)
        uploader = _uploader()

        assert uploader.check_directory() is False

    def test_returns_false_when_directory_unavailable(self, monkeypatch):
        class _NoMkdir(_FakeFTP):
            def mkd(self, path):
                raise OSError("550 Permission denied")

        no_mkdir = _NoMkdir()
        no_mkdir.cwd_fail = True
        monkeypatch.setattr(
            "src.services.fritzbox_images.ftplib.FTP",
            lambda *a, **k: no_mkdir,
        )
        uploader = _uploader()

        assert uploader.check_directory() is False


class TestFTPSSelection:
    """Plain FTP vs explicit FTPS selection."""

    def test_plain_fpt_uses_ftp(self, monkeypatch):
        fake = _FakeFTP()
        _patch_ftplib(monkeypatch, fake)
        uploader = _uploader(plain=True)

        uploader.sync_images([_contact(5)])

        assert fake.used_tls is False
        assert fake.prot_p_called is False

    def test_ftps_uses_ftp_tls_and_prot_p(self, monkeypatch):
        fake = _FakeFTP()
        _patch_ftplib(monkeypatch, fake)
        uploader = _uploader(plain=False)

        uploader.sync_images([_contact(5)])

        assert fake.used_tls is True
        assert fake.prot_p_called is True
