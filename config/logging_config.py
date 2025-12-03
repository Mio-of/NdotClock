"""Centralized logging configuration for the application."""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(
    log_level: int = logging.INFO,
    log_file: Optional[str] = None,
    verbose: bool = False
) -> logging.Logger:
    """Configure application-wide logging.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional path to log file. If None, logs only to console
        verbose: If True, set DEBUG level and detailed format
        
    Returns:
        Configured root logger
        
    Example:
        >>> logger = setup_logging(verbose=True)
        >>> logger.info("Application started")
    """
    if verbose:
        log_level = logging.DEBUG
    
    # Create formatter
    if verbose:
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    else:
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (optional)
    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(log_level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except Exception as e:
            root_logger.warning(f"Failed to create log file {log_file}: {e}")
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a specific module.
    
    Args:
        name: Module name (usually __name__)
        
    Returns:
        Logger instance
        
    Example:
        >>> logger = get_logger(__name__)
        >>> logger.debug("Debug message")
    """
    return logging.getLogger(name)


class QtLogFilter(logging.Filter):
    """Filter to suppress known non-critical Qt messages."""
    
    IGNORED_PATTERNS = [
        "GBM is not supported",
        "Fallback to Vulkan",
        "service_worker_storage",
        "Fontconfig error",
        "Release of profile requested",
        "QXcbConnection",
        "Could not load the Qt platform plugin",
    ]
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Filter out known non-critical Qt messages.
        
        Args:
            record: Log record to filter
            
        Returns:
            True if message should be logged, False otherwise
        """
        message = record.getMessage()
        for pattern in self.IGNORED_PATTERNS:
            if pattern in message:
                return False
        return True


def setup_qt_logging() -> None:
    """Configure Qt-specific logging to reduce noise."""
    qt_logger = logging.getLogger('Qt')
    qt_logger.setLevel(logging.WARNING)
    qt_logger.addFilter(QtLogFilter())
    
    # Suppress WebEngine debug messages
    webengine_logger = logging.getLogger('QtWebEngine')
    webengine_logger.setLevel(logging.ERROR)
