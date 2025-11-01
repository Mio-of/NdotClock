"""Application-wide constant values."""

__version__ = "1.2.8"
__github_repo__ = "Mio-of/NdotClock"
__github_branch__ = "main"
__github_api_commits_url__ = (
    f"https://api.github.com/repos/{__github_repo__}/commits/{__github_branch__}"
)
__github_version_file_path__ = "config/constants.py"  # исправлено: версия читается из фактического файла конфигурации
__github_version_file_url__ = (
    f"https://raw.githubusercontent.com/{__github_repo__}/{__github_branch__}/{__github_version_file_path__}"
)
__github_archive_url__ = (
    f"https://github.com/{__github_repo__}/archive/{__github_branch__}.zip"
)

# Targets copied during self-update in order of dependency importance
# исправлено: обновление теперь синхронизирует все ключевые директории
UPDATE_TARGETS = [
    "config",
    "logic",
    "ui",
    "resources",
    "ndot_clock_pyqt.py",
    "requirements.txt",
    "README.md",
]
