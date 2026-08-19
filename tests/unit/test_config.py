"""Unit tests for configuration loading and validation.

Tests the config loader module:
- FR-017: missing or empty `country_code` / `area_code` raise a clear,
  human-readable error
- General configuration validation and loading behavior
"""

import pytest

from src.config.loader import SyncConfig, load_config


def _write_config(tmp_path, content: str) -> str:
    """Write config content to a temp file and return its path."""
    config_path = tmp_path / "config.ini"
    config_path.write_text(content)
    return str(config_path)


def _build_config(regional_lines: str) -> str:
    """Build a full valid config with the given [regional] section lines."""
    return (
        "[general]\n"
        "name_order = first_name_first\n\n"
        "[fritzbox]\n"
        "url = https://fritz.box\n"
        "username = user\n"
        "password = pass\n"
        "target_book = CardDAV Sync\n"
        "country = DE\n"
        "region = DE\n\n"
        "[regional]\n"
        f"{regional_lines}\n"
        "[source_1]\n"
        "url = https://nextcloud.example.com/carddav\n"
        "username = user1\n"
        "password = pass1\n"
        "priority = 1\n"
    )


class TestFR017MandatoryRegionalFields:
    """FR-017: `country_code` and `area_code` are mandatory."""

    def test_missing_country_code_raises_clear_error(self, tmp_path):
        """Test that a missing country_code raises a clear error."""
        config = _build_config("area_code = 30\n")
        with pytest.raises(ValueError, match=r"regional\.country_code"):
            load_config(_write_config(tmp_path, config))

    def test_missing_country_code_mentions_fr017(self, tmp_path):
        """Test that the error message references FR-017."""
        config = _build_config("area_code = 30\n")
        with pytest.raises(ValueError) as excinfo:
            load_config(_write_config(tmp_path, config))
        assert "FR-017" in str(excinfo.value)

    def test_empty_country_code_raises_error(self, tmp_path):
        """Test that an empty country_code raises a clear error."""
        config = _build_config("country_code =\narea_code = 30\n")
        with pytest.raises(ValueError, match=r"regional\.country_code"):
            load_config(_write_config(tmp_path, config))

    def test_whitespace_country_code_raises_error(self, tmp_path):
        """Test that a whitespace-only country_code raises a clear error."""
        config = _build_config("country_code =    \narea_code = 30\n")
        with pytest.raises(ValueError, match=r"regional\.country_code"):
            load_config(_write_config(tmp_path, config))

    def test_missing_area_code_raises_clear_error(self, tmp_path):
        """Test that a missing area_code raises a clear error."""
        config = _build_config("country_code = +49\n")
        with pytest.raises(ValueError, match=r"regional\.area_code"):
            load_config(_write_config(tmp_path, config))

    def test_missing_area_code_mentions_fr017(self, tmp_path):
        """Test that the error message references FR-017."""
        config = _build_config("country_code = +49\n")
        with pytest.raises(ValueError) as excinfo:
            load_config(_write_config(tmp_path, config))
        assert "FR-017" in str(excinfo.value)

    def test_empty_area_code_raises_error(self, tmp_path):
        """Test that an empty area_code raises a clear error."""
        config = _build_config("country_code = +49\narea_code =\n")
        with pytest.raises(ValueError, match=r"regional\.area_code"):
            load_config(_write_config(tmp_path, config))

    def test_valid_regional_config_loads(self, tmp_path):
        """Test that a config with both mandatory fields loads correctly."""
        config = _build_config(
            "country_code = +49\narea_code = 30\ninternational_access_code = 00\n"
        )
        loaded = load_config(_write_config(tmp_path, config))

        assert isinstance(loaded, SyncConfig)
        assert loaded.regional.country_code == "+49"
        assert loaded.regional.area_code == "30"
        assert loaded.regional.international_access_code == "00"

    def test_international_access_code_defaults_to_00(self, tmp_path):
        """Test that international_access_code defaults to '00'."""
        config = _build_config("country_code = +49\narea_code = 30\n")
        loaded = load_config(_write_config(tmp_path, config))
        assert loaded.regional.international_access_code == "00"


class TestConfigValidation:
    """General config validation and loading behavior."""

    def test_missing_config_file_raises(self, tmp_path):
        """Test that a nonexistent config file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / "nonexistent.ini"))

    def test_missing_fritzbox_section_raises(self, tmp_path):
        """Test that a missing [fritzbox] section raises a clear error."""
        config = (
            "[general]\n"
            "name_order = first_name_first\n\n"
            "[regional]\n"
            "country_code = +49\n"
            "area_code = 30\n\n"
            "[source_1]\n"
            "url = https://nextcloud.example.com/carddav\n"
            "username = user1\n"
            "password = pass1\n"
            "priority = 1\n"
        )
        with pytest.raises(ValueError, match="fritzbox"):
            load_config(_write_config(tmp_path, config))

    def test_no_carddav_sources_raises(self, tmp_path):
        """Test that a config without sources raises a clear error."""
        config = (
            "[general]\n"
            "name_order = first_name_first\n\n"
            "[fritzbox]\n"
            "url = https://fritz.box\n"
            "username = user\n"
            "password = pass\n\n"
            "[regional]\n"
            "country_code = +49\n"
            "area_code = 30\n"
        )
        with pytest.raises(ValueError, match="No CardDAV sources"):
            load_config(_write_config(tmp_path, config))

    def test_invalid_fritzbox_url_raises(self, tmp_path):
        """Test that an invalid FritzBox URL raises a clear error."""
        config = _build_config("country_code = +49\narea_code = 30\n").replace(
            "https://fritz.box", "fritz.box"
        )
        with pytest.raises(ValueError, match="Invalid FritzBox URL"):
            load_config(_write_config(tmp_path, config))

    def test_duplicate_source_priority_raises(self, tmp_path):
        """Test that duplicate source priorities raise a clear error."""
        config = _build_config("country_code = +49\narea_code = 30\n") + (
            "[source_2]\n"
            "url = https://caldav.example.com/addressbook\n"
            "username = user2\n"
            "password = pass2\n"
            "priority = 1\n"
        )
        with pytest.raises(ValueError, match="Duplicate priority"):
            load_config(_write_config(tmp_path, config))

    def test_source_priority_gap_raises(self, tmp_path):
        """Test that non-sequential source priorities raise a clear error."""
        config = _build_config("country_code = +49\narea_code = 30\n") + (
            "[source_2]\n"
            "url = https://caldav.example.com/addressbook\n"
            "username = user2\n"
            "password = pass2\n"
            "priority = 3\n"
        )
        with pytest.raises(ValueError, match="without gaps"):
            load_config(_write_config(tmp_path, config))

    def test_inline_comment_ignored(self, tmp_path):
        """Test that inline comments in the regional section are stripped."""
        config = _build_config(
            "country_code = +49  # REQUIRED (FR-017)\narea_code = 30\n"
        )
        loaded = load_config(_write_config(tmp_path, config))
        assert loaded.regional.country_code == "+49"

    def test_sorted_sources_and_primary(self, tmp_path):
        """Test that sources are sorted by priority and primary is returned."""
        config = _build_config("country_code = +49\narea_code = 30\n") + (
            "[source_2]\n"
            "url = https://caldav.example.com/addressbook\n"
            "username = user2\n"
            "password = pass2\n"
            "priority = 2\n"
        )
        loaded = load_config(_write_config(tmp_path, config))

        assert [s.priority for s in loaded.sorted_sources] == [1, 2]
        assert loaded.get_primary_source().priority == 1

    def test_name_order_default(self, tmp_path):
        """Test that name_order defaults to first_name_first."""
        config = _build_config("country_code = +49\narea_code = 30\n")
        loaded = load_config(_write_config(tmp_path, config))
        assert loaded.general.name_order == "first_name_first"


def _build_env_config() -> str:
    """Build a valid config with NO credentials (to be supplied via env)."""
    return (
        "[general]\n"
        "name_order = first_name_first\n\n"
        "[fritzbox]\n"
        "url = https://fritz.box\n"
        "target_book = CardDAV Sync\n\n"
        "[regional]\n"
        "country_code = +49\n"
        "area_code = 30\n\n"
        "[source_1]\n"
        "url = https://nextcloud.example.com/carddav\n"
        "priority = 1\n"
    )


class TestEnvVarCredentials:
    """US2: credentials can be supplied via environment variables."""

    def test_env_fritzbox_username_overrides_config(self, tmp_path, monkeypatch):
        """Test that FRITZBOX_USERNAME overrides the config file value."""
        monkeypatch.delenv("FRITZBOX_USERNAME", raising=False)
        monkeypatch.setenv("FRITZBOX_USERNAME", "env_user")
        loaded = load_config(
            _write_config(
                tmp_path, _build_config("country_code = +49\narea_code = 30\n")
            )
        )
        assert loaded.fritzbox.username == "env_user"

    def test_env_fritzbox_password_overrides_config(self, tmp_path, monkeypatch):
        """Test that FRITZBOX_PASSWORD overrides the config file value."""
        monkeypatch.delenv("FRITZBOX_PASSWORD", raising=False)
        monkeypatch.setenv("FRITZBOX_PASSWORD", "env_pass")
        loaded = load_config(
            _write_config(
                tmp_path, _build_config("country_code = +49\narea_code = 30\n")
            )
        )
        assert loaded.fritzbox.password == "env_pass"

    def test_env_source_username_overrides_config(self, tmp_path, monkeypatch):
        """Test that CARDDAV_1_USERNAME overrides the config file value."""
        monkeypatch.delenv("CARDDAV_1_USERNAME", raising=False)
        monkeypatch.setenv("CARDDAV_1_USERNAME", "env_src_user")
        loaded = load_config(
            _write_config(
                tmp_path, _build_config("country_code = +49\narea_code = 30\n")
            )
        )
        assert loaded.sources[0].username == "env_src_user"

    def test_env_source_password_overrides_config(self, tmp_path, monkeypatch):
        """Test that CARDDAV_1_PASSWORD overrides the config file value."""
        monkeypatch.delenv("CARDDAV_1_PASSWORD", raising=False)
        monkeypatch.setenv("CARDDAV_1_PASSWORD", "env_src_pass")
        loaded = load_config(
            _write_config(
                tmp_path, _build_config("country_code = +49\narea_code = 30\n")
            )
        )
        assert loaded.sources[0].password == "env_src_pass"

    def test_env_only_credentials_load_successfully(self, tmp_path, monkeypatch):
        """Test that a config without credentials loads when env vars are set."""
        monkeypatch.delenv("FRITZBOX_USERNAME", raising=False)
        monkeypatch.delenv("FRITZBOX_PASSWORD", raising=False)
        monkeypatch.delenv("CARDDAV_1_USERNAME", raising=False)
        monkeypatch.delenv("CARDDAV_1_PASSWORD", raising=False)
        monkeypatch.setenv("FRITZBOX_USERNAME", "fb_user")
        monkeypatch.setenv("FRITZBOX_PASSWORD", "fb_pass")
        monkeypatch.setenv("CARDDAV_1_USERNAME", "src_user")
        monkeypatch.setenv("CARDDAV_1_PASSWORD", "src_pass")

        loaded = load_config(_write_config(tmp_path, _build_env_config()))

        assert loaded.fritzbox.username == "fb_user"
        assert loaded.fritzbox.password == "fb_pass"
        assert loaded.sources[0].username == "src_user"
        assert loaded.sources[0].password == "src_pass"

    def test_env_only_credentials_priority_two(self, tmp_path, monkeypatch):
        """Test env credentials keyed by priority (CARDDAV_2_*)."""
        config = _build_env_config() + (
            "[source_2]\n"
            "url = https://caldav.example.com/addressbook\n"
            "priority = 2\n"
        )
        for key in ("CARDDAV_1", "CARDDAV_2"):
            monkeypatch.delenv(f"{key}_USERNAME", raising=False)
            monkeypatch.delenv(f"{key}_PASSWORD", raising=False)
        monkeypatch.setenv("FRITZBOX_USERNAME", "fb")
        monkeypatch.setenv("FRITZBOX_PASSWORD", "fb")
        monkeypatch.setenv("CARDDAV_1_USERNAME", "u1")
        monkeypatch.setenv("CARDDAV_1_PASSWORD", "p1")
        monkeypatch.setenv("CARDDAV_2_USERNAME", "u2")
        monkeypatch.setenv("CARDDAV_2_PASSWORD", "p2")

        loaded = load_config(_write_config(tmp_path, config))

        assert loaded.sources[0].username == "u1"
        assert loaded.sources[1].username == "u2"
        assert loaded.sources[1].password == "p2"

    def test_empty_env_falls_back_to_config(self, tmp_path, monkeypatch):
        """Test that an empty env var is ignored and the file value is used."""
        monkeypatch.delenv("FRITZBOX_USERNAME", raising=False)
        monkeypatch.setenv("FRITZBOX_USERNAME", "")
        loaded = load_config(
            _write_config(
                tmp_path, _build_config("country_code = +49\narea_code = 30\n")
            )
        )
        assert loaded.fritzbox.username == "user"

    def test_env_value_is_stripped(self, tmp_path, monkeypatch):
        """Test that surrounding whitespace in env values is stripped."""
        monkeypatch.delenv("FRITZBOX_USERNAME", raising=False)
        monkeypatch.setenv("FRITZBOX_USERNAME", "  env_user  ")
        loaded = load_config(
            _write_config(
                tmp_path, _build_config("country_code = +49\narea_code = 30\n")
            )
        )
        assert loaded.fritzbox.username == "env_user"

    def test_env_overrides_all_credentials(self, tmp_path, monkeypatch):
        """Test that all four credential classes can be overridden at once."""
        for key in (
            "FRITZBOX_USERNAME",
            "FRITZBOX_PASSWORD",
            "CARDDAV_1_USERNAME",
            "CARDDAV_1_PASSWORD",
        ):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("FRITZBOX_USERNAME", "fbu")
        monkeypatch.setenv("FRITZBOX_PASSWORD", "fbp")
        monkeypatch.setenv("CARDDAV_1_USERNAME", "su")
        monkeypatch.setenv("CARDDAV_1_PASSWORD", "sp")

        loaded = load_config(
            _write_config(
                tmp_path, _build_config("country_code = +49\narea_code = 30\n")
            )
        )

        assert loaded.fritzbox.username == "fbu"
        assert loaded.fritzbox.password == "fbp"
        assert loaded.sources[0].username == "su"
        assert loaded.sources[0].password == "sp"
