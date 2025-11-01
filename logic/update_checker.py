"""Update checking and application self-update workflow."""

import json
import os
import shutil
import sys
import tempfile
import zipfile
from typing import Callable, Optional

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import QApplication

from config import (
    UPDATE_TARGETS,
    __github_api_commits_url__,
    __github_archive_url__,
    __github_repo__,
    __github_version_file_url__,
    __version__,
)


def _get_entry_script_path() -> str:
    """Resolve the main script path for performing self-update."""
    if getattr(sys, 'frozen', False):
        return sys.executable

    candidate = sys.argv[0] if sys.argv else ''
    if candidate:
        candidate_path = os.path.abspath(candidate)
        if os.path.isfile(candidate_path):
            return candidate_path

    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'ndot_clock_pyqt.py'))

DownloadPopupFactory = Callable[[object], object]


class UpdateChecker:
    """Check for updates directly from GitHub repository"""

    def __init__(self, parent_widget, download_popup_factory: Optional[DownloadPopupFactory] = None):
        self.parent = parent_widget
        # Fix: Add parent to prevent memory leak
        self.network_manager = QNetworkAccessManager(parent_widget)
        self.network_manager.finished.connect(self._on_update_check_finished)
        self.current_request_type = None  # 'check' or 'download'
        self.download_popup_factory = download_popup_factory
        self.download_progress_popup = None
        self._check_in_progress = False

    @staticmethod
    def _apply_redirect_policy(request: QNetworkRequest) -> None:
        """Enable automatic redirect following when supported by Qt build."""
        follow_attr = getattr(QNetworkRequest.Attribute, "FollowRedirectsAttribute", None)
        if follow_attr is not None:
            request.setAttribute(follow_attr, True)
            return

        redirect_attr = getattr(QNetworkRequest.Attribute, "RedirectPolicyAttribute", None)
        redirect_policy = getattr(QNetworkRequest.RedirectPolicy, "NoLessSafeRedirectPolicy", None)
        if redirect_attr is not None and redirect_policy is not None:
            request.setAttribute(redirect_attr, redirect_policy)

    def check_for_updates(self, silent: bool = False):
        """Check for updates from GitHub main branch

        Args:
            silent: If True, only show notification if update is available
        """
        if self._check_in_progress:
            if not silent:
                self.parent.show_notification(
                    "Update check already in progress...",
                    duration=2000,
                    notification_type="info",
                )
            return

        self.silent = silent
        self.current_request_type = 'check'
        self._check_in_progress = True

        # First, get the latest commit info to check version
        request = QNetworkRequest(QUrl(__github_api_commits_url__))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, f"NdotClock/{__version__}")
        self._apply_redirect_policy(request)
        self.network_manager.get(request)

    def _on_update_check_finished(self, reply: QNetworkReply):
        """Handle update check response"""
        if reply.error() != QNetworkReply.NetworkError.NoError:
            if not self.silent and self.current_request_type == 'check':
                self.parent.show_notification(
                    f"Failed to check for updates: {reply.errorString()}",
                    duration=4000,
                    notification_type="error"
                )
            if self.current_request_type in {'check', 'version_check'}:
                self._check_in_progress = False
            reply.deleteLater()
            return

        try:
            if self.current_request_type == 'check':
                # Parse commit info
                data = json.loads(reply.readAll().data().decode('utf-8'))
                commit_sha = data.get('sha', '')[:7]  # Short SHA
                commit_date = data.get('commit', {}).get('author', {}).get('date', '')
                commit_message = data.get('commit', {}).get('message', '').split('\n')[0]  # First line only

                # Now fetch the actual file to check version
                self.latest_commit_info = {
                    'sha': commit_sha,
                    'date': commit_date,
                    'message': commit_message
                }

                # Fetch the version file to extract version
                self.current_request_type = 'version_check'
                request = QNetworkRequest(QUrl(__github_version_file_url__))
                # исправлено: сравниваем версии по актуальному файлу конфигурации на GitHub
                request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, f"NdotClock/{__version__}")
                self._apply_redirect_policy(request)
                self.network_manager.get(request)

            elif self.current_request_type == 'version_check':
                # Parse version from raw file
                raw_content = reply.readAll().data().decode('utf-8')
                latest_version = self._extract_version_from_code(raw_content)

                # Debug: print version comparison
                print(f"[Update Check] Latest version from GitHub: {latest_version}")
                print(f"[Update Check] Current version: {__version__}")
                if latest_version:
                    comparison = self._compare_versions(latest_version, __version__)
                    print(f"[Update Check] Comparison result: {comparison} (1=newer, 0=same, -1=older)")

                if latest_version and self._compare_versions(latest_version, __version__) > 0:
                    # Update available
                    self._show_update_dialog(
                        latest_version,
                        f"https://github.com/{__github_repo__}/commit/{self.latest_commit_info['sha']}",
                        self.latest_commit_info['message'],
                        self.latest_commit_info['date']
                    )
                elif not self.silent:
                    self.parent.show_notification(
                        f"You are running the latest version ({__version__})",
                        duration=3000,
                        notification_type="success"
                    )
                self._check_in_progress = False

            elif self.current_request_type == 'download':
                # Download completed - install the update
                downloaded_data = reply.readAll().data()
                self._install_update(downloaded_data)

        except Exception as e:
            if not self.silent:
                self.parent.show_notification(
                    f"Error checking updates: {str(e)}",
                    duration=4000,
                    notification_type="error"
                )
            if self.current_request_type in {'check', 'version_check'}:
                self._check_in_progress = False
        finally:
            reply.deleteLater()

    def _extract_version_from_code(self, code: str) -> Optional[str]:
        """Extract version from Python code"""
        import re
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', code)
        if match:
            return match.group(1)
        return None

    def _compare_versions(self, v1: str, v2: str) -> int:
        """Compare two version strings

        Returns:
            1 if v1 > v2
            0 if v1 == v2
            -1 if v1 < v2
        """
        try:
            parts1 = [int(x) for x in v1.split('.')]
            parts2 = [int(x) for x in v2.split('.')]

            # Pad to same length
            while len(parts1) < len(parts2):
                parts1.append(0)
            while len(parts2) < len(parts1):
                parts2.append(0)

            for p1, p2 in zip(parts1, parts2):
                if p1 > p2:
                    return 1
                elif p1 < p2:
                    return -1
            return 0
        except:
            return 0

    def _show_update_dialog(self, version: str, commit_url: str, commit_message: str, commit_date: str):
        """Show update available dialog with auto-update option"""
        message = f"New version {version} available!\nCurrent: {__version__}\n\n{commit_message}"

        # Store version info for download
        self.latest_version_info = {
            'version': version,
            'url': commit_url,
            'message': commit_message
        }

        def on_confirm():
            self.start_download_update()

        self.parent.show_confirmation(
            "Update Available",
            message,
            on_confirm,
            confirm_text="Download & Install",
            cancel_text="Later"
        )

    def start_download_update(self):
        """Start downloading the update"""
        if self.download_popup_factory:
            self.download_progress_popup = self.download_popup_factory(self.parent)
            self.download_progress_popup.show()
            self.download_progress_popup.set_status("Connecting to GitHub...")

        # Start download
        self.current_request_type = 'download'
        request = QNetworkRequest(QUrl(__github_archive_url__))
        # исправлено: скачиваем zip-архив репозитория вместо одиночного скрипта
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, f"NdotClock/{__version__}")
        self._apply_redirect_policy(request)

        reply = self.network_manager.get(request)
        reply.downloadProgress.connect(self._on_download_progress)

    def _on_download_progress(self, bytes_received: int, bytes_total: int):
        """Update download progress"""
        if bytes_total > 0 and self.download_progress_popup:
            progress = int((bytes_received / bytes_total) * 100)
            self.download_progress_popup.set_progress(progress)

            # Format size
            mb_received = bytes_received / (1024 * 1024)
            mb_total = bytes_total / (1024 * 1024)
            self.download_progress_popup.set_status(
                f"Downloading... {mb_received:.1f} MB / {mb_total:.1f} MB"
            )

    def _install_update(self, archive_data: bytes):
        """Install the downloaded update"""
        import subprocess

        if self.download_progress_popup:
            self.download_progress_popup.set_progress(100)
            self.download_progress_popup.set_status("Installing update...")

        base_dir = os.path.abspath(os.path.join(_get_entry_script_path(), os.pardir))
        # исправлено: вычисляем корневой каталог проекта для копирования всех модулей
        temp_dir = tempfile.mkdtemp(prefix="ndot_update_")
        archive_path = os.path.join(temp_dir, "update.zip")
        replacements = []

        try:
            # Write archive to disk for ZipFile consumption
            with open(archive_path, 'wb') as archive_file:
                archive_file.write(archive_data)

            # Extract archive
            with zipfile.ZipFile(archive_path) as zip_file:
                zip_file.extractall(temp_dir)

            # Determine repo root inside archive
            extracted_root = None
            for entry in os.listdir(temp_dir):
                candidate = os.path.join(temp_dir, entry)
                if os.path.isdir(candidate) and entry != "__MACOSX":
                    extracted_root = candidate
                    break

            if extracted_root is None:
                raise RuntimeError("Unable to locate project root in archive")

            # Copy targets in priority order
            for target in UPDATE_TARGETS:
                src_path = os.path.join(extracted_root, target)
                if not os.path.exists(src_path):
                    continue  # No such path in archive; skip silently

                if self.download_progress_popup:
                    # исправлено: отображаем установку каждого модуля пользователю
                    self.download_progress_popup.set_status(f"Installing {target}...")

                dest_path = os.path.join(base_dir, target)
                backup_path = None

                if os.path.isdir(src_path):
                    backup_path = dest_path + ".backup"
                    if os.path.exists(backup_path):
                        shutil.rmtree(backup_path)
                    if os.path.exists(dest_path):
                        shutil.move(dest_path, backup_path)
                    shutil.copytree(src_path, dest_path)
                    replacements.append(("dir", dest_path, backup_path))
                else:
                    if os.path.exists(dest_path):
                        backup_path = dest_path + ".backup"
                        if os.path.exists(backup_path):
                            os.remove(backup_path)
                        shutil.copy2(dest_path, backup_path)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    shutil.copy2(src_path, dest_path)
                    replacements.append(("file", dest_path, backup_path))

            # Close progress popup
            if self.download_progress_popup:
                self.download_progress_popup.close()

            # Show restart confirmation
            def on_restart():
                # Fix: Ensure proper restart sequence
                python = sys.executable
                if getattr(sys, 'frozen', False):
                    command = [python]
                else:
                    command = [python, _get_entry_script_path()]
                # Use QTimer to delay restart until after quit
                QTimer.singleShot(200, lambda: subprocess.Popen(command))
                QApplication.quit()

            self.parent.show_confirmation(
                "Update Installed",
                f"Update to version {self.latest_version_info['version']} installed successfully!\n\nRestart the application to apply changes.",
                on_restart,
                confirm_text="Restart Now",
                cancel_text="Later"
            )

        except Exception as exc:
            # исправлено: восстанавливаем предыдущие файлы при любой ошибке установки
            for item_type, dest_path, backup_path in reversed(replacements):
                try:
                    if item_type == "dir":
                        if os.path.exists(dest_path):
                            shutil.rmtree(dest_path)
                        if backup_path and os.path.exists(backup_path):
                            shutil.move(backup_path, dest_path)
                    else:
                        if os.path.exists(dest_path):
                            os.remove(dest_path)
                        if backup_path and os.path.exists(backup_path):
                            shutil.move(backup_path, dest_path)
                except Exception as restore_error:
                    print(f"[Update Restore] Failed to restore {dest_path}: {restore_error}")

            if self.download_progress_popup:
                self.download_progress_popup.close()

            self.parent.show_notification(
                f"Update installation failed: {exc}",
                duration=5000,
                notification_type="error"
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
