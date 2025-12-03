"""Configuration package exposing application constants and localization data."""

from . import constants as _constants

__version__ = getattr(_constants, "__version__", "0.0.0")
__github_repo__ = getattr(_constants, "__github_repo__", "Mio-of/NdotClock")
__github_branch__ = getattr(_constants, "__github_branch__", "main")

if hasattr(_constants, "__github_api_commits_url__"):
    __github_api_commits_url__ = _constants.__github_api_commits_url__
else:  # Fallback for older installations
    __github_api_commits_url__ = (
        f"https://api.github.com/repos/{__github_repo__}/commits/{__github_branch__}"
    )

if hasattr(_constants, "__github_archive_url__"):
    __github_archive_url__ = _constants.__github_archive_url__
else:
    __github_archive_url__ = f"https://github.com/{__github_repo__}/archive/{__github_branch__}.zip"

__github_version_file_path__ = getattr(
    _constants, "__github_version_file_path__", "config/constants.py"
)
if hasattr(_constants, "__github_version_file_url__"):
    __github_version_file_url__ = _constants.__github_version_file_url__
else:
    __github_version_file_url__ = (
        f"https://raw.githubusercontent.com/{__github_repo__}/{__github_branch__}/{__github_version_file_path__}"
    )

UPDATE_TARGETS = getattr(
    _constants,
    "UPDATE_TARGETS",
    ["config", "logic", "ui", "resources", "ndot_clock_pyqt.py", "requirements.txt", "README.md"],
)

from .localization import WEEKDAYS, MONTHS, TRANSLATIONS
from .logging_config import setup_logging, get_logger, setup_qt_logging
from .settings import (
    ClockSettings,
    AutoBrightnessSettings,
    SlideConfig,
    Location,
    ColorRGB,
    Language,
)

__all__ = [
    "__version__",
    "__github_repo__",
    "__github_branch__",
    "__github_api_commits_url__",
    "__github_archive_url__",
    "__github_version_file_path__",
    "__github_version_file_url__",
    "UPDATE_TARGETS",
    "WEEKDAYS",
    "MONTHS",
    "TRANSLATIONS",
    "setup_logging",
    "get_logger",
    "setup_qt_logging",
    "ClockSettings",
    "AutoBrightnessSettings",
    "SlideConfig",
    "Location",
    "ColorRGB",
    "Language",
]
