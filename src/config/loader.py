"""Configuration loader for CardDAV to FritzBox sync utility.

Parses INI configuration file with the following structure:

[general]
name_order = first_name_first

[fritzbox]
url = https://fritz.box
username = your_username
password = your_password
target_book = CardDAV Sync
country = DE
region = DE

[regional]
country_code = +49                 # REQUIRED (FR-017)
area_code = 30                     # REQUIRED (FR-017)
international_access_code = 00     # REQUIRED for normalization (FR-005)

[source_1]
url = https://nextcloud.example.com
username = user1
password = pass1
priority = 1

[source_2]
url = https://calendar.example.com
username = user2
password = pass2
priority = 2
"""

import configparser
import os
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class CardDAVSourceConfig:
    """Configuration for a single CardDAV source."""

    url: str
    username: str
    password: str
    priority: int = 1

    def __post_init__(self):
        # Ensure priority is valid
        if self.priority < 1:
            self.priority = 1


@dataclass
class FritzBoxConfig:
    """Configuration for FritzBox connection and target."""

    url: str
    username: str
    password: str
    target_book: str = "CardDAV Sync"
    country: str = "DE"
    region: str = "DE"

    @property
    def host(self) -> str:
        """Extract hostname from URL."""
        return self.url.replace("https://", "").replace("http://", "")


@dataclass
class RegionalConfig:
    """Regional settings for phone number normalization.

    `country_code` and `area_code` are mandatory (spec.md FR-017).
    """

    country: str
    region: str
    country_code: str
    area_code: str
    international_access_code: str = "00"


@dataclass
class GeneralConfig:
    """General utility settings."""

    name_order: str = "first_name_first"  # "first_name_first" or "last_name_first"


@dataclass
class SyncConfig:
    """Complete configuration for CardDAV to FritzBox sync."""

    general: GeneralConfig
    fritzbox: FritzBoxConfig
    regional: RegionalConfig
    sources: List[CardDAVSourceConfig]

    @property
    def sorted_sources(self) -> List[CardDAVSourceConfig]:
        """Get sources sorted by priority (highest first)."""
        return sorted(self.sources, key=lambda x: x.priority)

    def get_primary_source(self) -> Optional[CardDAVSourceConfig]:
        """Get the highest priority source."""
        return self.sorted_sources[0] if self.sources else None


def load_config(config_path: str) -> SyncConfig:
    """Load configuration from INI file.

    Args:
        config_path: Path to INI configuration file

    Returns:
        SyncConfig object with all configuration loaded

    Raises:
        FileNotFoundError: If config file does not exist
        ValueError: If configuration is invalid or missing required fields
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
    # Preserve case sensitivity for field names
    parser.optionxform = lambda option: option

    # Read the configuration file
    parser.read(config_path)

    # Load general section
    general_config = _load_general_config(parser)

    # Load fritzbox section
    fritzbox_config = _load_fritzbox_config(parser)

    # Load regional section
    regional_config = _load_regional_config(parser, fritzbox_config)

    # Load all CardDAV source sections
    sources = _load_carddav_sources_config(parser)

    # Validate configuration
    _validate_config(general_config, fritzbox_config, sources)

    return SyncConfig(
        general=general_config,
        fritzbox=fritzbox_config,
        regional=regional_config,
        sources=sources,
    )


def _load_general_config(parser: configparser.ConfigParser) -> GeneralConfig:
    """Load general configuration section."""
    if not parser.has_section("general"):
        # Provide defaults if section missing
        return GeneralConfig()

    name_order = parser.get(
        "general", "name_order", fallback="first_name_first"
    ).lower()

    # Validate name_order value
    if name_order not in ["first_name_first", "last_name_first"]:
        raise ValueError(
            f"Invalid name_order value: {name_order}. "
            f"Must be 'first_name_first' or 'last_name_first'"
        )

    return GeneralConfig(name_order=name_order)


def _load_fritzbox_config(parser: configparser.ConfigParser) -> FritzBoxConfig:
    """Load FritzBox configuration section."""
    if not parser.has_section("fritzbox"):
        raise ValueError("Missing required 'fritzbox' section in configuration")

    # Required fields
    url = parser.get("fritzbox", "url")
    username = parser.get("fritzbox", "username")
    password = parser.get("fritzbox", "password")

    # Optional fields with defaults
    target_book = parser.get("fritzbox", "target_book", fallback="CardDAV Sync")
    country = parser.get("fritzbox", "country", fallback="DE")
    region = parser.get("fritzbox", "region", fallback="DE")

    return FritzBoxConfig(
        url=url,
        username=username,
        password=password,
        target_book=target_book,
        country=country,
        region=region,
    )


def _load_regional_config(
    parser: configparser.ConfigParser, fritzbox_config: FritzBoxConfig
) -> RegionalConfig:
    """Load regional configuration section.

    `country_code` and `area_code` are mandatory (FR-017): the loader raises a
    clear, human-readable error when either is missing or empty.
    """
    country = parser.get("regional", "country", fallback=fritzbox_config.country)
    region = parser.get("regional", "region", fallback=fritzbox_config.region)
    country_code = parser.get("regional", "country_code", fallback=None)
    area_code = parser.get("regional", "area_code", fallback=None)
    international_access_code = parser.get(
        "regional", "international_access_code", fallback="00"
    )

    if not country_code or not country_code.strip():
        raise ValueError(
            "Missing required 'regional.country_code' in the configuration "
            "(FR-017). Set country_code in the [regional] section, e.g. "
            "country_code = +49."
        )

    if not area_code or not area_code.strip():
        raise ValueError(
            "Missing required 'regional.area_code' in the configuration "
            "(FR-017). Set area_code in the [regional] section, e.g. "
            "area_code = 30."
        )

    return RegionalConfig(
        country=country,
        region=region,
        country_code=country_code.strip(),
        area_code=area_code.strip(),
        international_access_code=international_access_code.strip(),
    )


def _load_carddav_sources_config(
    parser: configparser.ConfigParser,
) -> List[CardDAVSourceConfig]:
    """Load all CardDAV source configuration sections."""
    sources = []

    # Find all source sections (source_1, source_2, etc.)
    for section in parser.sections():
        if section.startswith("source_"):
            try:
                # Required fields
                url = parser.get(section, "url")
                username = parser.get(section, "username")
                password = parser.get(section, "password")

                # Optional priority field (default to 1 if not specified)
                priority = parser.getint(section, "priority", fallback=1)

                sources.append(
                    CardDAVSourceConfig(
                        url=url, username=username, password=password, priority=priority
                    )
                )
            except (configparser.NoOptionError, ValueError) as e:
                raise ValueError(f"Invalid configuration in section [{section}]: {e}")

    if not sources:
        raise ValueError(
            "No CardDAV sources configured. At least one source section is required."
        )

    return sources


def _validate_config(
    general: GeneralConfig, fritzbox: FritzBoxConfig, sources: List[CardDAVSourceConfig]
) -> None:
    """Validate configuration consistency."""
    # Validate general config
    if general.name_order not in ["first_name_first", "last_name_first"]:
        raise ValueError(f"Invalid name_order: {general.name_order}")

    # Validate fritzbox config
    if not fritzbox.url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid FritzBox URL: {fritzbox.url}")

    if fritzbox.target_book.strip() == "":
        raise ValueError("FritzBox target_book cannot be empty")

    # Validate sources
    for source in sources:
        if not source.url.startswith(("http://", "https://")):
            raise ValueError(
                f"Invalid CardDAV URL for source {source.priority}: {source.url}"
            )

        if source.url.strip() == "":
            raise ValueError(f"Empty URL for source {source.priority}")

        if source.username.strip() == "":
            raise ValueError(f"Empty username for source {source.priority}")

        if source.password.strip() == "":
            raise ValueError(f"Empty password for source {source.priority}")

        # Check for duplicate priorities
        priority_count = sum(1 for s in sources if s.priority == source.priority)
        if priority_count > 1:
            raise ValueError(
                f"Duplicate priority {source.priority} for CardDAV sources"
            )

    # Check source ordering
    priorities = sorted([s.priority for s in sources])
    if priorities != list(range(1, len(sources) + 1)):
        raise ValueError("Source priorities must be 1, 2, 3... without gaps")


def print_config_summary(config: SyncConfig) -> None:
    """Print a summary of the loaded configuration."""
    print("Configuration Summary:")
    print("  General:")
    print(f"    Name Order: {config.general.name_order}")
    print("  FritzBox:")
    print(f"    Host: {config.fritzbox.host}")
    print(f"    Target Book: {config.fritzbox.target_book}")
    print(f"    Country: {config.fritzbox.country}")
    print(f"    Region: {config.fritzbox.region}")
    print("  Regional:")
    print(f"    Country Code: {config.regional.country_code}")
    print(f"    Area Code: {config.regional.area_code}")
    print(f"    International Access Code: {config.regional.international_access_code}")
    print(f"  CardDAV Sources ({len(config.sources)}):")
    for source in config.sorted_sources:
        print(
            f"    Source {source.priority}: {source.url} (username: {source.username})"
        )
