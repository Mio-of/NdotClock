"""Cross-platform helpers for managing application autostart."""

import logging
import os
import sys

logger = logging.getLogger(__name__)


def _get_entry_script_path() -> str:
    """Resolve the script path used when running in development mode."""
    if getattr(sys, 'frozen', False):
        return sys.executable

    candidate = sys.argv[0] if sys.argv else ''
    if candidate:
        candidate_path = os.path.abspath(candidate)
        if os.path.isfile(candidate_path):
            return candidate_path

    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'ndot_clock_pyqt.py'))


class AutostartManager:
    """Manage application autostart across different platforms"""

    @staticmethod
    def get_autostart_status() -> bool:
        """Check if autostart is enabled.
        
        Returns:
            True if autostart is enabled, False otherwise
        """
        try:
            if sys.platform == 'win32':
                return AutostartManager._check_windows_autostart()
            elif sys.platform == 'darwin':
                return AutostartManager._check_macos_autostart()
            else:  # Linux
                return AutostartManager._check_linux_autostart()
        except Exception as e:
            logger.error(f"Failed to check autostart status: {e}")
            return False

    @staticmethod
    def enable_autostart() -> bool:
        """Enable autostart for the application.
        
        Returns:
            True if autostart was enabled successfully, False otherwise
        """
        try:
            result = False
            if sys.platform == 'win32':
                result = AutostartManager._enable_windows_autostart()
            elif sys.platform == 'darwin':
                result = AutostartManager._enable_macos_autostart()
            else:  # Linux
                result = AutostartManager._enable_linux_autostart()
            
            if result:
                logger.info("Autostart enabled successfully")
            else:
                logger.warning("Failed to enable autostart")
            return result
        except Exception as e:
            logger.error(f"Failed to enable autostart: {e}")
            return False

    @staticmethod
    def disable_autostart() -> bool:
        """Disable autostart for the application.
        
        Returns:
            True if autostart was disabled successfully, False otherwise
        """
        try:
            result = False
            if sys.platform == 'win32':
                result = AutostartManager._disable_windows_autostart()
            elif sys.platform == 'darwin':
                result = AutostartManager._disable_macos_autostart()
            else:  # Linux
                result = AutostartManager._disable_linux_autostart()
            
            if result:
                logger.info("Autostart disabled successfully")
            else:
                logger.warning("Failed to disable autostart")
            return result
        except Exception as e:
            logger.error(f"Failed to disable autostart: {e}")
            return False

    # Windows implementation
    @staticmethod
    def _check_windows_autostart() -> bool:
        """Check Windows autostart via registry.
        
        Returns:
            True if registry key exists, False otherwise
        """
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                                0, winreg.KEY_READ)
            try:
                winreg.QueryValueEx(key, "NdotClock")
                winreg.CloseKey(key)
                return True
            except FileNotFoundError:
                winreg.CloseKey(key)
                return False
        except OSError as e:
            logger.debug(f"Failed to check Windows registry: {e}")
            return False

    @staticmethod
    def _enable_windows_autostart() -> bool:
        """Enable Windows autostart via registry.
        
        Returns:
            True if registry key was set successfully, False otherwise
        """
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                                0, winreg.KEY_SET_VALUE)

            # Get executable path
            if getattr(sys, 'frozen', False):
                exe_path = sys.executable
            else:
                # For development, use pythonw to avoid console window
                python_path = sys.executable.replace('python.exe', 'pythonw.exe')
                script_path = _get_entry_script_path()
                exe_path = f'"{python_path}" "{script_path}"'

            winreg.SetValueEx(key, "NdotClock", 0, winreg.REG_SZ, exe_path)
            winreg.CloseKey(key)
            logger.debug(f"Set Windows autostart registry key: {exe_path}")
            return True
        except OSError as e:
            logger.error(f"Failed to set Windows registry: {e}")
            return False

    @staticmethod
    def _disable_windows_autostart() -> bool:
        """Disable Windows autostart via registry"""
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                                0, winreg.KEY_SET_VALUE)
            try:
                winreg.DeleteValue(key, "NdotClock")
                winreg.CloseKey(key)
                return True
            except FileNotFoundError:
                winreg.CloseKey(key)
                return True  # Already disabled
        except Exception:
            return False

    # macOS implementation
    @staticmethod
    def _check_macos_autostart() -> bool:
        """Check macOS autostart via LaunchAgents"""
        plist_path = os.path.expanduser("~/Library/LaunchAgents/com.ndotclock.plist")
        return os.path.exists(plist_path)

    @staticmethod
    def _enable_macos_autostart() -> bool:
        """Enable macOS autostart via LaunchAgents"""
        plist_path = os.path.expanduser("~/Library/LaunchAgents/com.ndotclock.plist")

        # Get executable path
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = sys.executable
            script_path = _get_entry_script_path()

        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ndotclock</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe_path}</string>"""

        if not getattr(sys, 'frozen', False):
            plist_content += f"""
        <string>{script_path}</string>"""

        plist_content += """
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
"""

        try:
            os.makedirs(os.path.dirname(plist_path), exist_ok=True)
            with open(plist_path, 'w') as f:
                f.write(plist_content)
            return True
        except Exception:
            return False

    @staticmethod
    def _disable_macos_autostart() -> bool:
        """Disable macOS autostart via LaunchAgents"""
        plist_path = os.path.expanduser("~/Library/LaunchAgents/com.ndotclock.plist")
        try:
            if os.path.exists(plist_path):
                os.remove(plist_path)
            return True
        except Exception:
            return False

    # Linux implementation
    @staticmethod
    def _check_linux_autostart() -> bool:
        """Check Linux autostart via XDG autostart"""
        desktop_path = os.path.expanduser("~/.config/autostart/ndotclock.desktop")
        return os.path.exists(desktop_path)

    @staticmethod
    def _enable_linux_autostart() -> bool:
        """Enable Linux autostart via XDG autostart"""
        desktop_path = os.path.expanduser("~/.config/autostart/ndotclock.desktop")

        # Get executable path
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = f"{sys.executable} {_get_entry_script_path()}"

        desktop_content = f"""[Desktop Entry]
Type=Application
Name=Ndot Clock
Exec={exe_path}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
"""

        try:
            os.makedirs(os.path.dirname(desktop_path), exist_ok=True)
            with open(desktop_path, 'w') as f:
                f.write(desktop_content)
            # Make executable
            os.chmod(desktop_path, 0o755)
            return True
        except Exception:
            return False

    @staticmethod
    def _disable_linux_autostart() -> bool:
        """Disable Linux autostart via XDG autostart"""
        desktop_path = os.path.expanduser("~/.config/autostart/ndotclock.desktop")
        try:
            if os.path.exists(desktop_path):
                os.remove(desktop_path)
            return True
        except Exception:
            return False
