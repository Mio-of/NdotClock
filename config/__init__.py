"""Configuration package exposing application constants and localization data."""

from .constants import (
    __version__,
    __github_repo__,
    __github_branch__,
    __github_api_commits_url__,
    __github_archive_url__,
    __github_version_file_path__,
    __github_version_file_url__,
    UPDATE_TARGETS,
)
from .localization import WEEKDAYS, MONTHS, TRANSLATIONS

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
]
