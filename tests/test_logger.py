"""Tests for StageLogger."""

import logging
import pytest
from bhajan.logger import StageLogger


@pytest.fixture
def stage_logger():
    """Create a StageLogger instance for testing."""
    logger = logging.getLogger("test")
    logger.setLevel(logging.DEBUG)
    # Add a null handler to avoid "No handler found" warnings
    logger.addHandler(logging.NullHandler())
    return StageLogger(logger, "test_stage")


def test_stage_logger_info_with_args(stage_logger, caplog):
    """Test that info() accepts printf-style arguments."""
    with caplog.at_level(logging.INFO):
        stage_logger.info("Value: %d", 42)
    
    assert "[test_stage] Value: 42" in caplog.text


def test_stage_logger_info_with_multiple_args(stage_logger, caplog):
    """Test that info() accepts multiple printf-style arguments."""
    with caplog.at_level(logging.INFO):
        stage_logger.info("Values: %d, %f, %s", 1, 2.5, "test")
    
    assert "[test_stage] Values: 1, 2.500000, test" in caplog.text


def test_stage_logger_info_without_args(stage_logger, caplog):
    """Test that info() works without arguments."""
    with caplog.at_level(logging.INFO):
        stage_logger.info("Simple message")
    
    assert "[test_stage] Simple message" in caplog.text


def test_stage_logger_debug_with_args(stage_logger, caplog):
    """Test that debug() accepts printf-style arguments."""
    with caplog.at_level(logging.DEBUG):
        stage_logger.debug("Debug value: %s", "test")
    
    assert "[test_stage] Debug value: test" in caplog.text


def test_stage_logger_warning_with_args(stage_logger, caplog):
    """Test that warning() accepts printf-style arguments."""
    with caplog.at_level(logging.WARNING):
        stage_logger.warning("Warning: %s", "something")
    
    assert "[test_stage] Warning: something" in caplog.text


def test_stage_logger_error_with_args(stage_logger, caplog):
    """Test that error() accepts printf-style arguments."""
    with caplog.at_level(logging.ERROR):
        stage_logger.error("Error: %s", "something went wrong")
    
    assert "[test_stage] Error: something went wrong" in caplog.text


def test_stage_logger_with_path_object(stage_logger, caplog):
    """Test that info() works with Path objects using %s."""
    from pathlib import Path
    
    test_path = Path("/some/test/path")
    with caplog.at_level(logging.INFO):
        stage_logger.info("Path: %s", test_path)
    
    # Path gets converted to string, Windows may use backslashes
    assert "[test_stage] Path:" in caplog.text
    assert "some" in caplog.text
    assert "test" in caplog.text
    assert "path" in caplog.text


def test_stage_logger_with_float_formatting(stage_logger, caplog):
    """Test that info() works with float formatting like the bug had."""
    with caplog.at_level(logging.INFO):
        stage_logger.info("Size: %.1f MB", 123.456)
    
    assert "[test_stage] Size: 123.5 MB" in caplog.text
