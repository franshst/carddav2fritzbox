"""Logging utility for CardDAV to FritzBox sync CLI."""

import logging
import os
import sys
from typing import Optional


def setup_logger(
    name: str = "carddav2fritzbox", log_level: Optional[str] = None
) -> logging.Logger:
    """Configure and return a standard logger writing to sys.stdout/sys.stderr.

    Reads LOG_LEVEL from environment variable if log_level parameter is omitted.
    Default level is INFO.
    """
    if log_level is None:
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    level = getattr(logging, log_level, logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers if setup_logger is called multiple times
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)

        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
