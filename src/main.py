"""Main entry point for CardDAV to FritzBox sync CLI utility.

This module serves as the command-line interface for the CardDAV to FritzBox
Sync utility, coordinating the entire sync process from configuration loading
to contact synchronization and reporting.
"""

import sys
from typing import Optional

from src.config.loader import load_config, print_config_summary
from src.services.carddav_fetcher import CardDAVFetcher
from src.services.converter import ContactConverter
from src.services.fritzbox_uploader import FritzBoxUploader
from src.utils.logger import setup_logger, log_error_and_exit


def main() -> None:
    """Main CLI entry point.

    The execution flow is:
    1. Parse command-line arguments for config file
    2. Load and validate configuration
    3. Setup logging
    4. Initialize services with configuration
    5. Execute sync process
    6. Report results and handle errors
    """
    config_path = _parse_cli_args()

    try:
        logger = _setup_logging()

        logger.info("Starting CardDAV to FritzBox sync")

        config = _load_and_validate_config(config_path)
        print_config_summary(config)

        sync_services = _initialize_services(config)

        sync_result = _execute_sync_process(sync_services, logger)

        _report_sync_result(sync_result, logger)

    except Exception as e:
        logger.error(f"Sync failed: {e}")
        sys.exit(1)

    logger.info("Sync completed successfully")


def _parse_cli_args() -> str:
    """Parse command-line arguments.

    Returns:
        Configuration file path
    """
    if len(sys.argv) != 2 or sys.argv[1] != "--config":
        print("Usage: python3 src/main.py --config config.ini")
        sys.exit(1)

    config_path = sys.argv[2] if len(sys.argv) > 2 else "config.ini"
    return config_path


def _setup_logging():
    """Setup logging system.

    Returns:
        Configured logger instance
    """
    return setup_logger()


def _load_and_validate_config(config_path: str):
    """Load and validate configuration.

    Args:
        config_path: Path to configuration file

    Returns:
        Loaded configuration object

    Raises:
        Exception: If configuration loading or validation fails
    """
    config = load_config(config_path)
    print(f"Configuration loaded successfully from: {config_path}")
    return config


def _initialize_services(config):
    """Initialize all required services.

    Args:
        config: Loaded configuration object

    Returns:
        Dictionary of initialized services
    """
    logger = setup_logger()

    carddav_fetcher = CardDAVFetcher(config, logger)
    converter = ContactConverter(config, logger)
    fritzbox_uploader = FritzBoxUploader(config, logger)

    return {
        "carddav_fetcher": carddav_fetcher,
        "converter": converter,
        "fritzbox_uploader": fritzbox_uploader,
        "logger": logger,
    }


def _execute_sync_process(services, logger):
    """Execute the complete sync process.

    Args:
        services: Dictionary of initialized services
        logger: Logger instance

    Returns:
        Dictionary with sync results
    """
    carddav_fetcher = services["carddav_fetcher"]
    converter = services["converter"]
    fritzbox_uploader = services["fritzbox_uploader"]

    try:
        # Step 1: Fetch contacts from CardDAV sources
        raw_contacts = carddav_fetcher.fetch_all_contacts()
        logger.info(f"Fetched {len(raw_contacts)} contacts from CardDAV sources")

        # Step 2: Convert and normalize contacts
        normalized_contacts = converter.convert_to_standard_format(raw_contacts)
        logger.info(f"Normalized {len(normalized_contacts)} contacts")

        # Step 3: Merge duplicate contacts
        merged_contacts = converter.merge_contacts(normalized_contacts)
        logger.info(f"Merged {len(merged_contacts)} contacts (removed duplicates)")

        # Step 4: Upload to FritzBox
        upload_result = fritzbox_uploader.upload_contacts(merged_contacts)

        return {
            "success": True,
            "total_fetched": len(raw_contacts),
            "total_normalized": len(normalized_contacts),
            "total_merged": len(merged_contacts),
            "upload_result": upload_result,
        }

    except Exception as e:
        logger.error(f"Sync process failed: {e}")
        raise


def _report_sync_result(sync_result, logger):
    """Report sync results to user.

    Args:
        sync_result: Dictionary with sync results
        logger: Logger instance
    """
    if sync_result["success"]:
        print("\n" + "=" * 60)
        print("SYNC COMPLETED SUCCESSFULLY")
        print("=" * 60)
        print(f"  Total Contacts Fetched:     {sync_result['total_fetched']}")
        print(f"  Total Contacts Normalized:  {sync_result['total_normalized']}")
        print(f"  Total Contacts Merged:      {sync_result['total_merged']}")

        upload_result = sync_result["upload_result"]
        if upload_result["success"]:
            print(f"  Contacts Uploaded:          {upload_result.get('uploaded_count', 0)}")
            print(f"  Contacts Deleted:           {upload_result.get('deleted_count', 0)}")
            print(f"  Upload Time:                {upload_result.get('upload_time_seconds', 0):.2f}s")
        else:
            print(f"  Upload Failed:              {upload_result.get('error', 'Unknown error')}")

        print("=" * 60)
        print("\nSync completed successfully! The specified FritzBox address book has been updated.")
        print("You can verify the results in your FritzBox address book.")

    else:
        print(f"\nERROR: Sync failed - {sync_result.get('error', 'Unknown error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
