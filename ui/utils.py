import sys
import os

def get_resource_dir(subdir=''):
    """Get resource directory path, compatible with PyInstaller and development"""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable (PyInstaller)
        base_path = sys._MEIPASS
    else:
        # Running in development mode
        # UI module lives in ui/, resources sit at project root
        # Assuming this file is in ui/utils.py, so we go up two levels
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if subdir:
        return os.path.join(base_path, subdir)
    return base_path

def get_config_dir():
    """Get platform-specific user config directory for settings"""
    app_name = "Ndot Clock"

    if sys.platform == 'win32':
        # Windows: %APPDATA%\Ndot Clock
        config_dir = os.path.join(os.environ.get('APPDATA', ''), app_name)
    elif sys.platform == 'darwin':
        # macOS: ~/Library/Application Support/Ndot Clock
        config_dir = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', app_name)
    else:
        # Linux/Unix: ~/.config/ndot_clock
        config_dir = os.path.join(os.path.expanduser('~'), '.config', app_name)

    # Create directory if it doesn't exist
    os.makedirs(config_dir, exist_ok=True)
    return config_dir
