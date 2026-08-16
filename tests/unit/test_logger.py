"""Unit tests for logger utility and contact model."""

import logging
import os
import pytest
from src.models.contact import Contact, EmailAddress, PhoneNumber
from src.utils.logger import setup_logger


def test_contact_model_initialization():
    phone = PhoneNumber(number="+4930123456", type="mobile", prio=1)
    email = EmailAddress(email="john@example.com", classifier="private")
    contact = Contact(
        name="John Doe",
        phone_numbers=[phone],
        emails=[email],
        is_vip=True,
    )

    assert contact.name == "John Doe"
    assert len(contact.phone_numbers) == 1
    assert contact.phone_numbers[0].number == "+4930123456"
    assert contact.emails[0].classifier == "private"
    assert contact.is_vip is True


def test_setup_logger_default():
    logger = setup_logger("test_default_logger")
    assert logger.name == "test_default_logger"
    assert logger.level == logging.INFO


def test_setup_logger_env_override(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    logger = setup_logger("test_debug_logger", log_level=None)
    assert logger.level == logging.DEBUG
