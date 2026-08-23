"""Unit tests for the Docker-secret loader (T013)."""

import pytest

from docker.entrypoint import SecretLoaderError, load_secrets


@pytest.fixture()
def secrets_dir(tmp_path, monkeypatch):
    d = tmp_path / "secrets"
    d.mkdir()
    monkeypatch.setattr("docker.entrypoint.SECRETS_DIR", str(d))
    return d


def write_secret(secrets_dir, name, value):
    p = secrets_dir / name
    p.write_text(value + "\n")
    return p


def test_known_secret_is_mapped_and_stripped(secrets_dir):
    write_secret(secrets_dir, "fritzbox_password", "topsecret\n")
    env = load_secrets({"FRITZBOX_PASSWORD": ""})
    assert env["FRITZBOX_PASSWORD"] == "topsecret"


def test_carddav_numbered_mapping(secrets_dir):
    write_secret(secrets_dir, "carddav_2_password", "pw2")
    env = load_secrets({})
    assert env["CARDDAV_2_PASSWORD"] == "pw2"


def test_unknown_secret_files_are_ignored(secrets_dir):
    write_secret(secrets_dir, "some_other_service", "x")
    assert load_secrets({}) == {}


def test_existing_env_not_overwritten_by_empty_file(secrets_dir):
    """Empty/unreadable secret file treated as absent (precedence rule)."""
    write_secret(secrets_dir, "fritzbox_password", "  \n")
    env = load_secrets({"FRITZBOX_PASSWORD": "from-config"})
    assert env["FRITZBOX_PASSWORD"] == "from-config"


def test_expected_missing_secret_aborts_with_name(secrets_dir):
    with pytest.raises(SecretLoaderError) as exc:
        load_secrets({}, expected=["ftp_password"])
    assert "ftp_password" in str(exc.value)


def test_expected_present_secret_passes(secrets_dir):
    write_secret(secrets_dir, "smtp_password", "mailpw")
    assert load_secrets({}, expected=["smtp_password"]) == {"SMTP_PASSWORD": "mailpw"}


def test_secret_value_never_in_error_message(secrets_dir):
    write_secret(secrets_dir, "fritzbox_password", "veryhidden")
    with pytest.raises(SecretLoaderError) as exc:
        load_secrets({}, expected=["nonexistent_password"])
    assert "veryhidden" not in str(exc.value)
