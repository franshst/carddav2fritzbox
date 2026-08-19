"""Main entry point for CardDAV to FritzBox sync utility.

This module provides the command-line interface for the sync utility,
handling argument parsing, configuration loading, and orchestrating the
complete sync workflow.

Key features:
- Command-line argument parsing with comprehensive options
- Configuration file loading with validation
- Integration with all core services (fetcher, converter, uploader)
- Comprehensive logging and error handling
- Non-interactive execution suitable for cron jobs
- Progress reporting for monitoring
- Graceful failure handling with informative error messages
"""

import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from typing import Optional

from src.config.loader import load_config, print_config_summary
from src.services.carddav_fetcher import CardDAVFetcher
from src.services.converter import (
    PhoneNumberNormalizer,
    ImageConverter,
    process_contact_photos,
    validate_and_normalize_contact,
)
from src.services.fritzbox_uploader import FritzBoxUploader
from src.utils.logger import setup_logger


def parse_arguments():
    """Parse command-line arguments.

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="CardDAV to FritzBox Sync Utility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --config config.ini
  python main.py --config /path/to/config.conf --log-level DEBUG

The configuration file (INI format) should contain:
  - FritzBox connection details
  - CardDAV source credentials
  - Regional settings for phone number normalization
        """,
    )

    parser.add_argument(
        "--config", required=True, help="Path to INI configuration file"
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and show what would be synced, "
        "but don't actually sync",
    )

    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate configuration and exit without running sync",
    )

    return parser.parse_args()


def load_and_validate_config(config_path: str) -> Optional[object]:
    """Load and validate configuration file.

    Args:
        config_path: Path to configuration file

    Returns:
        Loaded configuration object, or None if validation fails
    """
    try:
        config = load_config(config_path)
        print_config_summary(config)
        return config
    except Exception as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
        return None


def run_sync(config, dry_run: bool = False) -> bool:
    """Run the complete CardDAV to FritzBox sync process.

    Args:
        config: Loaded configuration object
        dry_run: If True, only validate without actually syncing

    Returns:
        True if sync completes successfully, False otherwise
    """
    try:
        # Setup logger
        logger = setup_logger("carddav_sync", log_level="INFO")
        logger.info("Starting CardDAV to FritzBox sync process")

        # Initialize services
        logger.info("Initializing CardDAV fetcher...")
        fetcher = CardDAVFetcher(config, logger)

        logger.info("Initializing image converter...")
        converter = ImageConverter(logger)

        logger.info("Initializing phone number normalizer...")
        normalizer = PhoneNumberNormalizer(
            country_code=config.regional.country_code,
            area_code=config.regional.area_code,
            international_access_code=config.regional.international_access_code,
        )

        logger.info("Initializing FritzBox uploader...")
        uploader = FritzBoxUploader(config.fritzbox, logger, normalizer=normalizer)

        # Test FritzBox connection
        logger.info("Testing FritzBox connection...")
        if not uploader.test_connection():
            logger.error("Failed to connect to FritzBox")
            return False

        # Fetch contacts from CardDAV sources
        logger.info("Fetching contacts from CardDAV sources...")
        contacts = fetcher.fetch_and_parse_contacts()

        if not contacts:
            logger.warning("No contacts found in CardDAV sources")
            return True

        logger.info(f"Fetched {len(contacts)} contacts")

        # Merge duplicate contacts across sources by identity (FR-004/FR-018)
        logger.info("Merging duplicate contacts across sources...")
        contacts = fetcher.merge_contacts(contacts)

        # Process and normalize contacts
        logger.info("Processing and normalizing contacts...")
        normalized_contacts = []

        for i, contact in enumerate(contacts):
            # Process photo
            contact = process_contact_photos(contact, converter)

            # Validate and normalize contact
            validated_contact = validate_and_normalize_contact(contact, normalizer)
            normalized_contacts.append(validated_contact)

            logger.info(
                f"Processed contact {i + 1}/{len(contacts)}: "
                f"{validated_contact.name}"
            )

        if dry_run:
            logger.info("Dry run mode - showing contact summary:")
            for contact in normalized_contacts:
                print(
                    f"  - {contact.name}: {len(contact.phone_numbers)} phones, "
                    f"{len(contact.emails)} emails"
                )
            logger.info("Dry run completed successfully")
            return True

        # Upload contacts to FritzBox (target book is resolved by name via TR-064)
        logger.info("Uploading contacts to FritzBox...")
        success = uploader.upload_phonebook(
            normalized_contacts,
            config.fritzbox.target_book,
            phonebook_id=None,
        )

        if success:
            logger.info("Sync process completed successfully")
            return True
        else:
            logger.error("Sync process failed")
            return False

    except Exception as e:
        logger.error(f"Unexpected error during sync: {e}")
        return False


def print_help_and_exit():
    """Print help information and exit."""
    help_text = """
CardDAV to FritzBox Sync Utility
================================

This utility synchronizes contacts from multiple CardDAV sources to a FritzBox device.

Usage:
  python main.py --config config.ini

Configuration file requirements:
  - [general] section with name_order setting
  - [fritzbox] section with connection details
  - [regional] section with country/region codes
  - Multiple [source_X] sections for CardDAV sources

Example configuration:

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

source_2
url = https://caldav.example.com
username = user2
password = pass2
priority = 2

Commands:
  --config PATH      Path to configuration file (required)
  --log-level LEVEL  Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  --dry-run          Show what would be synced without actually doing it
  --validate-only    Validate configuration and exit

Exit codes:
  0 - Success
  1 - Configuration error
  2 - Connection error
  3 - Sync error
  4 - General error
    """
    print(help_text)
    sys.exit(1)


def main():
    """Main entry point for the sync utility."""
    args = parse_arguments()

    # Setup logging early for error reporting
    logger = setup_logger("carddav_sync", log_level=args.log_level)

    logger.info("CardDAV to FritzBox Sync Utility starting")
    logger.info(f"Config file: {args.config}")

    # Load and validate configuration
    if args.validate_only:
        config = load_and_validate_config(args.config)
        if config:
            print("✓ Configuration is valid")
            return 0
        else:
            print("✗ Configuration validation failed", file=sys.stderr)
            return 1

    config = load_and_validate_config(args.config)
    if not config:
        return 1

    # Run sync process
    success = run_sync(config, dry_run=args.dry_run)

    if success:
        logger.info("Sync completed successfully")
        return 0
    else:
        logger.error("Sync failed")
        return 3


if __name__ == "__main__":
    sys.exit(main())
