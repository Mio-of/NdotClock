import os
from typing import Optional
from PyQt6.QtCore import QUrl, QTimer, Qt
from PyQt6.QtGui import QColor
# Note: QGraphicsOpacityEffect removed - causes window recreation with WebEngine
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

from ui.utils import get_config_dir


class SilentWebEnginePage(QWebEnginePage):
    """Кастомная страница webview которая подавляет JavaScript логи"""
    
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        """Подавляем JavaScript консольные сообщения"""
        # Игнорируем все JS логи
        pass


class WebviewManager:
    def __init__(self, parent):
        self.parent = parent
        self.webview: Optional[QWebEngineView] = None
        self.profile: Optional[QWebEngineProfile] = None  # Fix: Keep profile reference
        self.current_url = ""
        self.page_loaded = False
        self.error_message = ""
        self.error_notified = False
        self.load_timeout_timer: Optional[QTimer] = None

    def _prepare_url(self, raw_url: str, *, default_scheme: str = "https") -> Optional[QUrl]:
        """Normalize user-provided URL before loading it into webviews."""
        url_text = (raw_url or "").strip()
        if not url_text:
            return None

        url = QUrl(url_text)
        if not url.isValid() or not url.scheme():
            url = QUrl(f"{default_scheme}://{url_text}")

        if not url.isValid() or url.scheme().lower() not in {"http", "https"}:
            return None

        return url

    def create_webview(self):
        """Create universal web view for any website"""
        if self.webview is None:
            cookies_dir = os.path.join(get_config_dir(), "cookies")
            os.makedirs(cookies_dir, exist_ok=True)

            # Fix: Store profile reference to prevent garbage collection
            self.profile = QWebEngineProfile("webview_profile", self.parent)
            self.profile.setPersistentStoragePath(cookies_dir)
            self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)

            page = SilentWebEnginePage(self.profile, self.parent)

            self.webview = QWebEngineView(self.parent)
            self.webview.setPage(page)
            
            # Note: Do NOT use hide()/show() on WebEngineView!
            # It causes the parent window to close/reopen due to compositor conflicts.
            # Instead, we move the webview off-screen when not needed.
            self.webview.setGeometry(-10000, -10000, 800, 600)
            self.webview.show()  # Always keep visible, just off-screen
            
            self.webview.setUpdatesEnabled(False)

            self.webview.loadFinished.connect(self.on_webview_load_finished)

            settings = self.webview.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)  # Allow HTTP for local servers
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)

            self.webview.page().setBackgroundColor(QColor(255, 255, 255))

            self.webview.installEventFilter(self.parent)
            self.webview.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
            
            border_radius = int(16 * self.parent.scale_factor)
            self.webview.setStyleSheet(f"""
                QWebEngineView {{
                    border-radius: {border_radius}px;
                    background: white;
                }}
            """)
            self.webview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            
            self.webview.setUpdatesEnabled(True)

    def load_url(self, url: str):
        """Load URL in webview"""
        # Ensure webview exists (should be created once in __init__)
        if not self.webview:
            self.create_webview()
            
        url_object = self._prepare_url(url)
        if url_object is None:
            self.error_message = "Invalid URL"
            self.page_loaded = False
            self.error_notified = False
            return False
            
        new_url = url_object.toString()
        # Check if we are already on this URL (loaded or loading)
        if self.current_url == new_url:
            if self.page_loaded:
                # Already loaded - just return success without reloading
                return True
            if not self.error_message:
                # Already loading this URL and no error yet - don't restart
                return True
            # If there was an error, fall through to retry loading
            
        # Only update state and load if URL is different or there was an error
        self.current_url = new_url
        self.error_message = ""
        self.error_notified = False
        self.page_loaded = False
        
        # Set timeout for page load (10 seconds)
        # Fix: Reuse existing timer to prevent memory leak
        if self.load_timeout_timer:
            self.load_timeout_timer.stop()
        else:
            self.load_timeout_timer = QTimer(self.parent)
            self.load_timeout_timer.setSingleShot(True)
            self.load_timeout_timer.timeout.connect(self._on_load_timeout)
        self.load_timeout_timer.start(10000)
        
        self.webview.setUrl(url_object)
        return True

    def show_webview(self, geometry):
        """Show webview with specified geometry"""
        if not self.webview:
            return False
        
        if not self.page_loaded:
            # Page is still loading - keep webview off-screen but with correct size
            current_geom = self.webview.geometry()
            if (current_geom.width() != geometry.width() or 
                current_geom.height() != geometry.height()):
                self.webview.setGeometry(-10000, -10000, geometry.width(), geometry.height())
            self.webview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            return False
        
        # Page is loaded - move webview to correct position
        current_geom = self.webview.geometry()
        if (current_geom.x() != geometry.x() or 
            current_geom.y() != geometry.y() or
            current_geom.width() != geometry.width() or 
            current_geom.height() != geometry.height()):
            self.webview.setGeometry(geometry)
        
        self.webview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        return True

    def hide_webview(self):
        """Hide webview by moving it off-screen (don't use hide() - causes window recreation)"""
        if self.webview:
            self.webview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.webview.setGeometry(-10000, -10000, 1, 1)

    def on_webview_load_finished(self, success: bool):
        """Handle webview page load completion"""
        if self.load_timeout_timer:
            self.load_timeout_timer.stop()
            
        if success:
            self.page_loaded = True
            self.error_message = ""
            self.error_notified = False
            # Don't enable mouse events here - let parent decide via show_webview()
            # The webview is still off-screen until parent calls show_webview()
        else:
            self.error_message = "Failed to load page"
            self.page_loaded = False
            # Move webview off-screen on error
            if self.webview:
                self.hide_webview()
                
        # Notify parent to update UI (callback handles update logic)
        if hasattr(self.parent, 'on_webview_load_finished_callback'):
            self.parent.on_webview_load_finished_callback(success)

    def _on_load_timeout(self):
        """Handle load timeout"""
        self.error_message = "Page load timeout"
        self.page_loaded = False
        if self.webview:
            self.hide_webview()
        if hasattr(self.parent, 'update'):
            self.parent.update()

    def cleanup(self):
        """Clean up webview and profiles to prevent memory leaks"""
        # Fix: Stop and cleanup timer properly
        if self.load_timeout_timer:
            self.load_timeout_timer.stop()
            self.load_timeout_timer.deleteLater()
            self.load_timeout_timer = None
            
        if self.webview:
            # Fix: Disconnect signals before deleting to prevent callbacks on deleted object
            try:
                self.webview.loadFinished.disconnect(self.on_webview_load_finished)
            except (TypeError, RuntimeError):
                pass  # Signal was not connected or already disconnected
            self.webview.setParent(None)
            self.webview.deleteLater()
            self.webview = None
        
        # Fix: Cleanup profile
        if self.profile:
            self.profile = None
