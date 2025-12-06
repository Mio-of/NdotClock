import os
from typing import Optional
from PyQt6.QtCore import QUrl, QTimer, Qt, QRectF, pyqtSignal, pyqtSlot, QObject
from PyQt6.QtGui import QColor, QPainterPath, QRegion
from PyQt6.QtWebChannel import QWebChannel
# Note: QGraphicsOpacityEffect removed - causes window recreation with WebEngine
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

from ui.utils import get_config_dir


class KeyboardBridge(QObject):
    """Bridge to communicate between JavaScript and Python for keyboard"""
    keyboardRequested = pyqtSignal(str, str)  # element_id, current_value
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    @pyqtSlot(str, str)
    def requestKeyboard(self, element_id: str, current_value: str):
        """Called from JavaScript when input is focused"""
        self.keyboardRequested.emit(element_id, current_value)


class SilentWebEnginePage(QWebEnginePage):
    """Кастомная страница webview которая подавляет JavaScript логи"""
    
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        """Подавляем JavaScript консольные сообщения"""
        # Игнорируем все JS логи
        pass


class WebviewManager:
    def __init__(self, parent):
        self.parent = parent
        self.webviews: dict[str, QWebEngineView] = {}  # Cache: url -> view
        self.current_key: Optional[str] = None
        self.profile: Optional[QWebEngineProfile] = None
        
        # Cache geometry to avoid redundant updates
        self._last_mask_size: Optional[tuple[int, int]] = None
        self._last_geometry: Optional[tuple[int, int, int, int]] = None
        
        # Scroll position cache per URL
        self._scroll_positions: dict[str, tuple[int, int]] = {}  # url -> (x, y)

    @property
    def webview(self) -> Optional[QWebEngineView]:
        """Backwards compatibility: get current webview"""
        return self.webviews.get(self.current_key) if self.current_key else None

    @property
    def page_loaded(self) -> bool:
        """Backwards compatibility: get current page load status"""
        view = self.webview
        return getattr(view, 'page_loaded', False) if view else False

    @page_loaded.setter
    def page_loaded(self, value: bool):
        """Backwards compatibility: set current page load status"""
        view = self.webview
        if view:
            view.page_loaded = value

    @property
    def error_message(self) -> str:
        """Backwards compatibility: get current error message"""
        view = self.webview
        return getattr(view, 'error_message', "") if view else ""
        
    @property
    def current_url(self) -> str:
        """Backwards compatibility: get current url key"""
        return self.current_key if self.current_key else ""

    @current_url.setter
    def current_url(self, value: str):
        """Backwards compatibility: set current url key"""
        self.current_key = value if value else None

    def _border_radius_px(self) -> int:
        scale = getattr(self.parent, 'scale_factor', 1.0) or 1.0
        return max(8, int(12 * scale))

    def _apply_mask(self, width: int, height: int):
        view = self.webview
        if not view or width <= 0 or height <= 0:
            return
        size_key = (width, height)
        if size_key == self._last_mask_size:
            return
        self._last_mask_size = size_key
        border_radius = self._border_radius_px()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, width, height), border_radius, border_radius)
        region = QRegion(path.toFillPolygon().toPolygon())
        view.setMask(region)

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

    def _ensure_profile(self):
        """Initialize shared profile if needed"""
        if self.profile is None:
            cookies_dir = os.path.join(get_config_dir(), "cookies")
            os.makedirs(cookies_dir, exist_ok=True)

            self.profile = QWebEngineProfile("webview_profile", self.parent)
            self.profile.setPersistentStoragePath(cookies_dir)
            self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)

            # Enable Disk Cache for optimization
            cache_dir = os.path.join(get_config_dir(), "cache")
            os.makedirs(cache_dir, exist_ok=True)
            self.profile.setCachePath(cache_dir)
            self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)

    def create_webview(self):
        """Initialize profile (webview creation is now lazy in load_url)"""
        self._ensure_profile()

    def _create_webview_instance(self, url_key: str) -> QWebEngineView:
        """Create a new webview instance for the given URL"""
        self._ensure_profile()
        
        page = SilentWebEnginePage(self.profile, self.parent)
        view = QWebEngineView(self.parent)
        view.setPage(page)
        
        # Setup WebChannel for keyboard bridge
        channel = QWebChannel(page)
        bridge = KeyboardBridge(view)
        bridge.keyboardRequested.connect(self._on_keyboard_requested)
        channel.registerObject("keyboardBridge", bridge)
        page.setWebChannel(channel)
        view._keyboard_bridge = bridge
        
        # Initialize view state
        view.page_loaded = False
        view.error_message = ""
        view.error_notified = False
        view.load_timeout_timer = None
        
        # Store URL key on the view for reference
        view._url_key = url_key

        view.setUpdatesEnabled(False)
        # Start off-screen (don't call show() - it can break parent fullscreen on some WMs)
        view.setGeometry(-10000, -10000, 800, 600)
        view.setVisible(True)
        view.lower()  # Keep behind other widgets
        view.setUpdatesEnabled(True)

        view.loadFinished.connect(lambda success: self.on_webview_load_finished(view, success))
        view.urlChanged.connect(lambda url: self._on_url_changed(view, url))

        settings = view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True)
        # Enable touch scrolling
        if hasattr(QWebEngineSettings.WebAttribute, 'TouchIconsEnabled'):
            settings.setAttribute(QWebEngineSettings.WebAttribute.TouchIconsEnabled, True)

        view.page().setBackgroundColor(QColor(30, 30, 30))  # Dark background
        view.installEventFilter(self.parent)
        view.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        # Ensure child widget (focusProxy) also accepts touch events
        if view.focusProxy():
            view.focusProxy().setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        
        border_radius = self._border_radius_px()
        view.setStyleSheet(f"QWebEngineView {{ border-radius: {border_radius}px; background: #1e1e1e; }}")
        
        # Enable dark mode preference
        view.page().profile().setHttpUserAgent(
            view.page().profile().httpUserAgent() + " prefers-color-scheme: dark"
        )
        view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        
        view.setUpdatesEnabled(True)
        return view

    def load_url(self, url: str):
        """Load URL in webview (find existing or create new)"""
        url_object = self._prepare_url(url)
        if url_object is None:
            # Handle invalid URL - maybe assume current view?
            return False
            
        new_url_key = url_object.toString()
        
        # Switch logic
        if self.current_key != new_url_key:
            # Hide previous view if it exists
            if self.current_key and self.current_key in self.webviews:
                self._hide_view_instance(self.webviews[self.current_key])
            
            self.current_key = new_url_key
            
            # Reset geometry cache since we switched views
            self._last_geometry = None
            self._last_mask_size = None

        # Check if we have a cached view for this URL
        if new_url_key in self.webviews:
            # View exists - reuse it!
            view = self.webviews[new_url_key]
            # We don't need to reload unless it failed previously or is empty
            if view.page_loaded:
                return True
            if not view.error_message:
                # Already loading
                return True
            # Fall through to retry if error
        else:
            # Create new view
            view = self._create_webview_instance(new_url_key)
            self.webviews[new_url_key] = view
            
        # Perform load
        view.error_message = ""
        view.error_notified = False
        view.page_loaded = False
        
        # Timer setup
        if view.load_timeout_timer:
            view.load_timeout_timer.stop()
        else:
            view.load_timeout_timer = QTimer(self.parent)
            view.load_timeout_timer.setSingleShot(True)
            # Use partial or lambda to capture view
            view.load_timeout_timer.timeout.connect(lambda: self._on_load_timeout(view))
            
        view.load_timeout_timer.start(10000)
        
        view.setUrl(url_object)
        return True

    def show_webview(self, geometry):
        """Show current webview with specified geometry"""
        view = self.webview
        if not view:
            return False
        
        geom_tuple = (geometry.x(), geometry.y(), geometry.width(), geometry.height())
        needs_geometry_update = self._last_geometry != geom_tuple
        
        if not view.page_loaded:
            if needs_geometry_update:
                current_geom = view.geometry()
                if current_geom.x() < 0 or current_geom.y() < 0:
                    view.setGeometry(-10000, -10000, geometry.width(), geometry.height())
                    self._apply_mask(geometry.width(), geometry.height())
            view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            return False
        
        if needs_geometry_update:
            view.setUpdatesEnabled(False)
            view.setGeometry(geometry)
            self._apply_mask(geometry.width(), geometry.height())
            view.setUpdatesEnabled(True)
            self._last_geometry = geom_tuple
        
        view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        return True

    def _hide_view_instance(self, view: QWebEngineView):
        """Helper to hide a specific view"""
        if view:
            view.setUpdatesEnabled(False)
            view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            view.setGeometry(-10000, -10000, 1, 1)
            view.setUpdatesEnabled(True)

    def hide_webview(self):
        """Hide current webview"""
        self._hide_view_instance(self.webview)
        self._last_mask_size = None
        self._last_geometry = None

    def on_webview_load_finished(self, view: QWebEngineView, success: bool):
        """Handle webview page load completion"""
        if getattr(view, 'load_timeout_timer', None):
            view.load_timeout_timer.stop()
            
        if success:
            view.page_loaded = True
            view.error_message = ""
            view.error_notified = False
            # Inject keyboard helper script
            self._inject_keyboard_script(view)
        else:
            view.error_message = "Failed to load page"
            view.page_loaded = False
            self._hide_view_instance(view)
        
        # Fix: Re-apply fullscreen if it was lost (some WMs break it when webviews load)
        if hasattr(self.parent, 'is_fullscreen') and self.parent.is_fullscreen:
            if not self.parent.isFullScreen():
                self.parent.showFullScreen()
            
        # Only notify parent if this is the current view
        if self.webview == view:
            if hasattr(self.parent, 'on_webview_load_finished_callback'):
                self.parent.on_webview_load_finished_callback(success)
    
    def _inject_keyboard_script(self, view: QWebEngineView):
        """Inject JavaScript to handle input focus for on-screen keyboard"""
        script = """
        (function() {
            if (window._keyboardHelperInstalled) return;
            window._keyboardHelperInstalled = true;
            
            // Force dark color scheme
            var meta = document.createElement('meta');
            meta.name = 'color-scheme';
            meta.content = 'dark';
            document.head.appendChild(meta);
            
            // Override prefers-color-scheme media query
            try {
                Object.defineProperty(window, 'matchMedia', {
                    writable: true,
                    value: function(query) {
                        if (query === '(prefers-color-scheme: dark)') {
                            return { matches: true, media: query, addListener: function(){}, removeListener: function(){}, addEventListener: function(){}, removeEventListener: function(){} };
                        }
                        if (query === '(prefers-color-scheme: light)') {
                            return { matches: false, media: query, addListener: function(){}, removeListener: function(){}, addEventListener: function(){}, removeEventListener: function(){} };
                        }
                        return window._originalMatchMedia ? window._originalMatchMedia(query) : { matches: false, media: query, addListener: function(){}, removeListener: function(){}, addEventListener: function(){}, removeEventListener: function(){} };
                    }
                });
            } catch(e) {}
            
            // Load QWebChannel
            var script = document.createElement('script');
            script.src = 'qrc:///qtwebchannel/qwebchannel.js';
            script.onload = function() {
                new QWebChannel(qt.webChannelTransport, function(channel) {
                    window.keyboardBridge = channel.objects.keyboardBridge;
                    
                    // Handle focus on input/textarea
                    document.addEventListener('focusin', function(e) {
                        var el = e.target;
                        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                            var type = el.type || 'text';
                            if (type !== 'hidden' && type !== 'checkbox' && type !== 'radio' && type !== 'submit' && type !== 'button') {
                                window._activeInput = el;
                                window.keyboardBridge.requestKeyboard(el.id || 'input', el.value || '');
                            }
                        }
                    });
                });
            };
            document.head.appendChild(script);
        })();
        """
        view.page().runJavaScript(script)
    
    def _on_keyboard_requested(self, element_id: str, current_value: str):
        """Handle keyboard request from webview"""
        if hasattr(self.parent, 'show_webview_keyboard'):
            self.parent.show_webview_keyboard(element_id, current_value)
    
    def set_input_value(self, value: str):
        """Set value to the active input in webview"""
        view = self.webview
        if view and view.page_loaded:
            escaped = value.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n')
            script = f"""
            if (window._activeInput) {{
                window._activeInput.value = '{escaped}';
                window._activeInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
            }}
            """
            view.page().runJavaScript(script)

    def _on_url_changed(self, view: QWebEngineView, url: QUrl):
        """Handle URL change - save current URL to slide settings"""
        if not view.page_loaded:
            return  # Don't save during initial load
        
        new_url = url.toString()
        url_key = getattr(view, '_url_key', None)
        
        if url_key and new_url and hasattr(self.parent, 'update_webview_url'):
            self.parent.update_webview_url(url_key, new_url)
    
    def _on_load_timeout(self, view: QWebEngineView):
        """Handle load timeout"""
        view.error_message = "Page load timeout"
        view.page_loaded = False
        self._hide_view_instance(view)
        
        if self.webview == view and hasattr(self.parent, 'update'):
            self.parent.update()

    def cleanup(self):
        """Clean up all webviews"""
        for view in self.webviews.values():
            timer = getattr(view, 'load_timeout_timer', None)
            if timer:
                timer.stop()
                timer.deleteLater()
            
            view.setParent(None)
            view.deleteLater()
            
        self.webviews.clear()
        self.current_key = None
        
        if self.profile:
            self.profile.deleteLater()
            self.profile = None
        
        self._last_mask_size = None
        self._last_geometry = None
