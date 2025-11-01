"""Application entry point for Ndot Clock."""

import os
import sys

from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
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
)
from ui import NDotClockSlider

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


def qt_message_handler(mode, context, message):
    """Фильтр Qt логов - подавляем известные не-критичные сообщения"""
    # Игнорируем известные не-критичные сообщения
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
    
    # Показываем только критичные ошибки
    if mode == QtMsgType.QtCriticalMsg or mode == QtMsgType.QtFatalMsg:
        print(f"Qt: {message}", file=sys.stderr)


def main():
    # Подавляем JavaScript логи из Chromium (ДО создания QApplication)
    os.environ['QT_LOGGING_RULES'] = 'qt.webenginecontext.debug=false'
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-logging --log-level=3'
    
    # Подавляем Qt логи
    qInstallMessageHandler(qt_message_handler)
    
    app = QApplication(sys.argv)
    clock = NDotClockSlider()
    clock.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
