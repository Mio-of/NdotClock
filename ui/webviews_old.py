import os
from typing import Optional
from PyQt6.QtCore import QUrl, QTimer, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QGraphicsOpacityEffect
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

            profile = QWebEngineProfile("webview_profile", self.parent)
            profile.setPersistentStoragePath(cookies_dir)
            profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)

            page = SilentWebEnginePage(profile, self.parent)

            self.webview = QWebEngineView(self.parent)
            self.webview.setPage(page)
            
            self.webview.setGeometry(-10000, -10000, 800, 600)
            self.webview.hide()
            
            self.webview.setUpdatesEnabled(False)

            opacity_effect = QGraphicsOpacityEffect(self.webview)
            opacity_effect.setOpacity(0.0)
            self.webview.setGraphicsEffect(opacity_effect)
            self.webview.opacity_effect = opacity_effect

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
        if not self.webview:
            self.create_webview()
            
        url_object = self._prepare_url(url)
        if url_object is None:
            self.error_message = "Invalid URL"
            self.page_loaded = False
            self.error_notified = False
            return False
            
        self.current_url = url_object.toString()
        self.error_message = ""
        self.error_notified = False
        self.page_loaded = False
        
        # Set timeout for page load (10 seconds)
        if self.load_timeout_timer:
            self.load_timeout_timer.stop()
        self.load_timeout_timer = QTimer()
        self.load_timeout_timer.setSingleShot(True)
        self.load_timeout_timer.timeout.connect(self._on_load_timeout)
        self.load_timeout_timer.start(10000)
        
        self.webview.setUrl(url_object)
        return True

    def show_webview(self, geometry):
        """Show webview with specified geometry"""
        if not self.webview or not self.page_loaded:
            return False
            
        self.webview.setGeometry(geometry)
        self.webview.show()
        self.webview.raise_()
        self.webview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        
        # Apply opacity
        if hasattr(self.webview, 'opacity_effect') and self.webview.opacity_effect:
            self.webview.opacity_effect.setOpacity(1.0)
        
        return True

    def hide_webview(self):
        """Hide webview"""
        if self.webview:
            self.webview.hide()
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
            # Start fade-in animation if visible
            if self.webview and self.webview.isVisible():
                self._animate_fade_in()
        else:
            self.error_message = "Failed to load page"
            self.page_loaded = False
            if self.webview and self.webview.isVisible():
                self.hide_webview()
                
        # Notify parent to update UI
        if hasattr(self.parent, 'update'):
            self.parent.update()

    def _on_load_timeout(self):
        """Handle load timeout"""
        self.error_message = "Page load timeout"
        self.page_loaded = False
        if self.webview and self.webview.isVisible():
            self.hide_webview()
        if hasattr(self.parent, 'update'):
            self.parent.update()

    def _animate_fade_in(self):
        """Animate webview fade-in"""
        if not hasattr(self.webview, 'opacity_effect') or not self.webview.opacity_effect:
            return
        # Simple fade-in - could be enhanced with QPropertyAnimation
        self.webview.opacity_effect.setOpacity(1.0)

    def cleanup(self):
        """Clean up webview and profiles to prevent memory leaks"""
        if self.load_timeout_timer:
            self.load_timeout_timer.stop()
            
        if self.webview:
            self.webview.setParent(None)
            self.webview.deleteLater()
            self.webview = None
                self.youtube_loaded = False
                self.youtube_error_notified = False
                self.youtube_last_url = youtube_url or ""

    def preload_home_assistant_sync(self):
        """Preload Home Assistant synchronously before UI is shown"""
        if self.home_assistant_webview and not self.home_assistant_loaded:
            ha_url = None
            for slide in self.parent.slides:
                if slide['type'] == SlideType.HOME_ASSISTANT:
                    ha_url = slide['data'].get('url', 'http://homeassistant.local:8123/')
                    break

            url_object = self._prepare_url(ha_url or "", default_scheme="http")
            if url_object:
                self.home_assistant_last_url = url_object.toString()
                self.home_assistant_error_notified = False
                self.home_assistant_webview.setGeometry(-10000, -10000, 100, 100)
                QTimer.singleShot(10000, lambda: self.parent._check_home_assistant_load_timeout())
                self.home_assistant_webview.setUrl(url_object)
                self.home_assistant_loaded = True
                self.home_assistant_error_message = ""
            else:
                self.home_assistant_error_message = self.parent._tr("webview_error")
                self.home_assistant_loaded = False
                self.home_assistant_error_notified = False
                self.home_assistant_last_url = ha_url or ""

    def cleanup(self):
        """Clean up webviews and profiles to prevent memory leaks."""
        for attr in ('youtube_webview', 'home_assistant_webview'):
            webview = getattr(self, attr, None)
            if webview:
                webview.stop()  # Stop loading
                page = webview.page()
                if page:
                    # Clean up profile to prevent memory leak
                    profile = page.profile()
                    if profile and not profile.isOffTheRecord():
                        # Only delete non-shared profiles
                        profile.deleteLater()
                    page.deleteLater()
                webview.hide()
                webview.setParent(None)
                webview.deleteLater()
                setattr(self, attr, None)

