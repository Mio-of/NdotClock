"""Application entry point for Ndot Clock."""

import logging
import os
import sys

from PyQt6.QtCore import Qt, QtMsgType, qInstallMessageHandler
from PyQt6.QtWidgets import QApplication

from config import (
    __github_api_commits_url__,
    __github_archive_url__,
    __github_branch__,
    __github_repo__,
    __github_version_file_path__,
    __github_version_file_url__,
    __version__,
    UPDATE_TARGETS,
    setup_logging,
    setup_qt_logging,
)
from ui import NDotClockSlider

# Setup logging
logger = setup_logging(
    log_level=logging.INFO,
    verbose=os.getenv('NDOT_VERBOSE', '').lower() in ('1', 'true', 'yes')
)
setup_qt_logging()

__all__ = [
    "__version__",
    "__github_repo__",
    "__github_branch__",
    "__github_api_commits_url__",
    "__github_archive_url__",
    "__github_version_file_path__",
    "__github_version_file_url__",
    "UPDATE_TARGETS",
    "main",
]


def qt_message_handler(mode: QtMsgType, context, message: str) -> None:
    """Filter Qt logs - suppress known non-critical messages.
    
    Args:
        mode: Qt message type (Debug, Warning, Critical, Fatal)
        context: Qt message context
        message: Log message text
    """
    qt_logger = logging.getLogger('Qt')
    
    # Ignore known non-critical messages
    ignored_patterns = [
        "GBM is not supported",
        "Fallback to Vulkan",
        "service_worker_storage",
        "Fontconfig error",
        "Release of profile requested",
    ]
    
    for pattern in ignored_patterns:
        if pattern in message:
            return
    
    # Log based on severity
    if mode == QtMsgType.QtCriticalMsg:
        qt_logger.critical(f"Qt Critical: {message}")
    elif mode == QtMsgType.QtFatalMsg:
        qt_logger.critical(f"Qt Fatal: {message}")
    elif mode == QtMsgType.QtWarningMsg:
        qt_logger.warning(f"Qt Warning: {message}")
    elif mode == QtMsgType.QtDebugMsg:
        qt_logger.debug(f"Qt Debug: {message}")


def main() -> int:
    """Main application entry point.
    
    Returns:
        Application exit code
    """
    logger.info(f"Starting N-Dot Clock v{__version__}")
    
    # Suppress JavaScript logs from Chromium (BEFORE creating QApplication)
    os.environ['QT_LOGGING_RULES'] = 'qt.webenginecontext.debug=false'
    
    # Performance flags for Chromium
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = (
        '--disable-logging --log-level=3 '
        '--ignore-gpu-blacklist '
        '--enable-gpu-rasterization '
        '--enable-zero-copy '
        '--enable-native-gpu-memory-buffers '
        '--canvas-oop-rasterization'
    )
    
    try:
        # Enable OpenGL context sharing (critical for WebEngine performance)
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
        
        # Create QApplication FIRST before installing message handler
        app = QApplication(sys.argv)
        
        # Now install Qt message handler AFTER QApplication is created
        qInstallMessageHandler(qt_message_handler)
        
        clock = NDotClockSlider()
        # Use showFullScreen() directly if fullscreen mode is enabled
        # This prevents flickering on some window managers (especially on RPi)
        if clock.is_fullscreen:
            clock.showFullScreen()
        else:
            clock.show()
        logger.info("Application initialized successfully")
        return app.exec()
    except Exception as e:
        logger.exception(f"Fatal error in main application: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
