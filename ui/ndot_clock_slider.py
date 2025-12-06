"""Main UI slider implementation for Ndot Clock."""

import json
import math
import os
import sys
import time
import webbrowser
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from PyQt6.QtCore import (
    QEvent,
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    QRectF,
    QPoint,
    QPointF,
    pyqtProperty,
    QTimer,
    Qt,
    QUrl,
)
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QIcon,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QRadialGradient,
    QRegion,
)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from urllib.parse import urlencode

from config import (
    MONTHS as MONTHS_MAP,
    TRANSLATIONS as TRANSLATIONS_MAP,
    WEEKDAYS as WEEKDAYS_MAP,
    __version__,
)
from logic import (
    AutostartManager,
    AmbientLightMonitor,
    JsonParserThread,
    SystemBacklightController,
    UpdateChecker,
)
from ui.animations import AnimatedPanel, AnimatedSlideContainer, SlideType
from ui.controls import ModernColorButton, ModernSlider
from ui.popups import ConfirmationPopup, DownloadProgressPopup, NotificationPopup, WiFiPopup, TextInputPopup
from ui.brightness import BrightnessManager
from ui.webviews import WebviewManager
from ui.settings_manager import SettingsManager
from ui.task_queue import TaskQueue


class BrightnessOverlay(QWidget):
    """Transparent overlay for software brightness control."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._opacity = 0.0
        self.hide()

    def set_opacity(self, opacity: float):
        """Set overlay opacity (0.0 - 1.0)."""
        self._opacity = max(0.0, min(1.0, opacity))
        if self._opacity > 0.001:
            self.show()
            self.raise_()
        else:
            self.hide()
        self.update()

    def paintEvent(self, event):
        if self._opacity <= 0:
            return
        painter = QPainter(self)
        painter.setBrush(QColor(0, 0, 0, int(self._opacity * 255)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(self.rect())


class NDotClockSlider(QWidget):
    """Main clock application with slider interface"""

    INACTIVITY_TIMEOUT = 60000  # 1 minute in milliseconds

    @staticmethod
    def get_resource_dir(subdir=''):
        """Get resource directory path, compatible with PyInstaller and development"""
        if getattr(sys, 'frozen', False):
            # Running as compiled executable (PyInstaller)
            base_path = sys._MEIPASS
        else:
            # Running in development mode
            # UI module lives in ui/, resources sit at project root
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            # исправлено: ресурсы (шрифты/иконки) снова ищутся в корне проекта

        if subdir:
            return os.path.join(base_path, subdir)
        return base_path

    @staticmethod
    def get_config_dir():
        """Get config directory inside resources folder for portability"""
        # Use the same logic as get_resource_dir to find the correct path
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
        config_dir = os.path.join(base_path, 'resources')
        os.makedirs(config_dir, exist_ok=True)
        return config_dir

    WEEKDAYS = WEEKDAYS_MAP
    MONTHS = MONTHS_MAP
    TRANSLATIONS = TRANSLATIONS_MAP

    def __init__(self):
        super().__init__()

        # Load fonts
        self.font_family = "Arial"
        resources_dir = self.get_resource_dir('resources')
        if os.path.exists(resources_dir):
            for file in os.listdir(resources_dir):
                if file.lower().endswith(('.ttf', '.otf')):
                    font_path = os.path.join(resources_dir, file)
                    font_id = QFontDatabase.addApplicationFont(font_path)
                    if font_id != -1:
                        families = QFontDatabase.applicationFontFamilies(font_id)
                        if families:
                            self.font_family = families[0]
                            break
        
        # Initialize Managers
        self.settings_manager = SettingsManager(self.get_config_dir())
        settings = self.settings_manager.load_settings()
        
        # State
        self._manual_brightness = settings['user_brightness']
        self._digit_color = settings['digit_color']
        self._background_color = settings['background_color']
        self._colon_color = settings['colon_color']
        self.current_language = settings['language']
        self.slides = settings['slides']
        self._ensure_slide_order()  # Ensure CLOCK first, ADD last
        self.location_lat = settings['location']['lat']
        self.location_lon = settings['location']['lon']
        self.location_city = settings['location'].get('city', '')
        self.is_fullscreen = settings['fullscreen']
        
        # Initialize Brightness Manager
        self.brightness_manager = BrightnessManager(self, self.settings_manager.default_settings)
        self._initial_settings = settings  # Store for lazy initialization
        self.brightness_manager.brightness_changed.connect(self._on_brightness_changed)
        self.brightness_manager.error_occurred.connect(
            lambda msg: self.show_notification(msg, notification_type="error")
        )
        self.brightness_manager.auto_brightness_toggled.connect(self._on_auto_brightness_toggled)

        # Initialize Webview Manager
        self.scale_factor = 1.0  # ensure available for dependent components
        self.webview_manager = WebviewManager(self)
        
        # Initialize Task Queue for lazy initialization
        self.task_queue = TaskQueue(self)
        
        # Derived settings
        self._digit_color_scaled = QColor(self._digit_color)
        self._colon_color_scaled = QColor(self._colon_color)
        self._date_color = QColor(self._digit_color)
        self._date_font_size = 18
        self._date_gap = 8
        # Fix: Add LRU limit to prevent memory leak
        self._dot_pixmap_cache: Dict[Tuple[int, int, bool], QPixmap] = {}
        self._dot_pixmap_cache_max_size = 200  # LRU limit for dot patterns
        
        # UI Setup
        self.setWindowTitle("Ndot Clock")
        self.resize(800, 480)
        self.setMinimumSize(800, 480)

        # Scaling factor for UI elements
        self.base_width = 800
        self.base_height = 480

        # Ленивая инициализация webview - создаём только при первом обращении
        self._webview_init_pending = False
        self._webview_initialized = False
        
        # Software brightness overlay
        self.brightness_overlay = BrightnessOverlay(self)
        
        # Digit patterns
        self.setup_digit_patterns()

        self.brightness_slider: Optional[ModernSlider] = None
        self.auto_brightness_checkbox: Optional[QCheckBox] = None
        self._edit_mode_entry_slide = 0

        # ARM optimization: Pre-calculate breathing animation lookup table (100 steps)
        self._breathing_lookup = []
        for i in range(100):
            t_val = (math.sin(i / 100.0 * 2 * math.pi - math.pi/2) + 1) / 2
            intensity = t_val * t_val * (3 - 2 * t_val)  # Smoothstep
            self._breathing_lookup.append(intensity)
        self._breathing_frame = 0  # Current frame in breathing cycle

        # ARM optimization: Cache for complete gradient dots (including halo) - матовый вид
        self._glow_dot_cache: Dict[Tuple[int, int, int, int], QPixmap] = {}  # (radius, r, g, b) -> pixmap
        self._glow_dot_cache_max_size = 300  # LRU limit - increased for better ARM performance

        # ARM optimization: SVG weather icon pixmap cache
        self._svg_weather_cache: Dict[Tuple[int, int, int], QPixmap] = {}  # (code, is_day, size) -> pixmap
        self._svg_weather_cache_max_size = 20  # Max 20 different weather icons

        # Fix: Prevent webview fade animation memory leak
        self._webview_fade_animations = []
        self._max_webview_fade_animations = 5  # Limit concurrent fade animations

        # Digit change animation state
        self._last_time_string = ""  # Track previous time to detect changes
        self._digit_animations: Dict[int, Dict[str, float]] = {}  # {position: {'progress': 0.0-1.0, 'old_digit': '0', 'new_digit': '1'}}
        self._digit_animation_duration = 0.4  # 400ms animation duration

        # Update checker
        self.update_checker = UpdateChecker(self, self._create_download_progress_popup)

        # State
        self.current_slide = 0
        self.edit_mode = False
        self._edit_transition_active = False
        self._active_edit_animations: Set[QPropertyAnimation] = set()
        self.card_edit_mode = False
        self.current_edit_index: Optional[int] = None
        self.active_panel_type: Optional[Tuple[str, Optional[int]]] = None
        self._i18n_widgets: Dict[str, List[Tuple[object, str, Dict[str, object]]]] = {}
        self.breathing_time = 0.0
        self.breathing_speed = 0.01
        self._last_update_second = -1  # Track last second for time change detection
        self._timer_interval_state = 'normal'  # Track timer interval state
        self.nav_hidden = False
        self.nav_hide_timer = QTimer(self)
        self.nav_hide_timer.timeout.connect(self.hide_navigation)
        self._nav_opacity = 1.0
        
        # Clock return timer for auto-return to clock after inactivity
        self.clock_return_timer = QTimer(self)
        self.clock_return_timer.setSingleShot(True)
        self.clock_return_timer.timeout.connect(self.return_to_clock)

        # Fix: Swipe smoothing for stable dragging (no throttling, use smoothing instead)
        self._drag_smoothing_alpha = 0.3  # Lower = smoother but more lag, higher = more responsive
        self._smoothed_offset = 0.0
        self._last_raw_offset = 0.0

        # Fix: Velocity prediction for smoother swipe release
        self._drag_velocity_history = []  # Track last N positions for velocity calculation
        self._drag_velocity_history_size = 5
        self.nav_opacity_animation = QPropertyAnimation(self)
        self.nav_opacity_animation.setTargetObject(self)
        self.nav_opacity_animation.setPropertyName(b"navOpacity")
        self.nav_opacity_animation.setDuration(300)
        self.nav_opacity_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._edit_panel_ratios: Optional[Tuple[float, float]] = None
        self._youtube_opened_slides: Set[int] = set()  # Track which YouTube slides were auto-opened
        # Webviews are now managed by self.webview_manager
        self._webview_mouse_start: Optional[QPoint] = None  # Track mouse start position for swipe detection
        self._active_webview_for_swipe: Optional[QWebEngineView] = None  # Currently swiped webview
        self._active_webview_type: Optional[SlideType] = None
        self._webview_was_transparent = False
        self._youtube_page_loaded = False  # Track if YouTube page finished loading
        self._home_assistant_page_loaded = False  # Track if Home Assistant page finished loading
        # YouTube state
        self._youtube_loaded = False
        self._youtube_error_message = ""
        self._youtube_error_notified = False
        self._youtube_last_url = ""
        # Home Assistant state
        self._home_assistant_loaded = False
        self._home_assistant_error_message = ""
        self._home_assistant_error_notified = False
        self._home_assistant_last_url = ""
        # Note: is_fullscreen is loaded from settings earlier in __init__

        # Mouse state for long press and dragging
        self.mouse_pressed = False
        self.press_start_pos = QPoint()
        self.press_start_time = 0
        self.is_dragging = False
        self.drag_start_x = 0
        self.drag_current_offset = 0.0
        self.long_press_timer = QTimer(self)
        self.long_press_timer.setSingleShot(True)
        self.long_press_timer.timeout.connect(self.on_long_press)

        # Card reordering in edit mode
        self.is_reordering_card = False
        self.reorder_drag_index: Optional[int] = None
        self.reorder_target_index: Optional[int] = None
        self.reorder_drag_offset = QPointF()
        self.reorder_swap_animations: Dict[int, QPropertyAnimation] = {}
        self.reorder_card_offsets: Dict[int, QPointF] = {}
        self.reorder_activation_timer = QTimer(self)
        self.reorder_activation_timer.setSingleShot(True)
        self.reorder_activation_timer.timeout.connect(self._activate_card_reordering)
        self.reorder_pending_index: Optional[int] = None
        self.reorder_auto_scroll_timer = QTimer(self)
        self.reorder_auto_scroll_timer.setInterval(120)
        self.reorder_auto_scroll_timer.setSingleShot(False)
        self.reorder_auto_scroll_timer.timeout.connect(self._perform_reorder_auto_scroll)
        self.reorder_auto_scroll_direction = 0
        self._last_reorder_cursor_pos: Optional[QPoint] = None
        self._skip_release_processing = False  # исправлено: предотвращаем срабатывание свайпа после кликов по контролам

        # Fix: Add timeout detection for webview load hangs
        self._webview_load_timeouts = {'youtube': False, 'home_assistant': False}
        self._language_control_layout = None  # исправлено: переиспользуем геометрию кнопок языка
        self._is_new_card = False  # Track if we are creating a new card to handle cancel correctly
        
        # Animation container
        self.slide_container = AnimatedSlideContainer(self)
        
        # Animations
        self.offset_animation = QPropertyAnimation(self.slide_container, b"offset_x")
        self.offset_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.offset_animation.setDuration(500)
        self.offset_animation.finished.connect(self._on_edit_transition_animation_finished)

        self.scale_animation = QPropertyAnimation(self.slide_container, b"scale")
        self.scale_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.scale_animation.setDuration(600)
        self.scale_animation.finished.connect(self._on_edit_transition_animation_finished)

        self.offset_y_animation = QPropertyAnimation(self.slide_container, b"offset_y")
        self.offset_y_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.offset_y_animation.setDuration(600)
        self.offset_y_animation.finished.connect(self._on_edit_transition_animation_finished)
        
        # Network manager for weather
        self.network_manager = QNetworkAccessManager(self)
        self.weather_data = None
        self.weather_loading = False
        self.weather_status_message = ""  # For UI feedback on errors
        
        # Fix: JSON parser thread for non-blocking parsing
        # Separate threads for location and weather parsing to avoid race conditions
        self.location_parser_thread: Optional[JsonParserThread] = None
        self.weather_parser_thread: Optional[JsonParserThread] = None
        self.location_loading = False

        # Fix: Cache QFont objects for performance (ARM optimization) with LRU limits
        self._font_cache: Dict[Tuple[str, int], QFont] = {}
        self._font_cache_max_size = 50  # LRU limit to prevent unbounded growth
        self._fontmetrics_cache: Dict[Tuple[str, int], QFontMetrics] = {}
        self._fontmetrics_cache_max_size = 50

        # Edit panel
        self.edit_panel = None
        self.panel_animation = None
        self.panel_opacity_animation = None
        self.panel_scale_animation = None
        self._panel_opacity = 0.0

        # Perform heavy initialization lazily to unblock startup
        QTimer.singleShot(100, self._perform_lazy_initialization)
        
        # Restore window state (fullscreen) shortly after startup
        QTimer.singleShot(300, self._restore_window_state)

        # Main timer - ARM-optimized with dynamic intervals
        # Start with 16ms for smooth animations, but will adjust dynamically
        self.main_timer = QTimer(self)
        self.main_timer.timeout.connect(self.on_timeout)
        self.main_timer.start(16)

        # Weather timer
        self.weather_timer = QTimer(self)
        self.weather_timer.timeout.connect(self.fetch_weather)
        self.weather_timer.start(600000)  # 10 minutes



    def _perform_lazy_initialization(self):
        """Perform heavy initialization tasks using TaskQueue to prevent UI freezes."""
        
        # 1. Configure Brightness Manager
        # This might start the camera, so we do it first but safely
        def init_brightness():
            if hasattr(self, '_initial_settings'):
                self.brightness_manager.configure(self._initial_settings)
                del self._initial_settings
        
        self.task_queue.add_task(init_brightness, "Init Brightness", delay_ms=100)

        # 2. Preload webviews (staggered)
        # We add each webview load as a separate task with delay
        for i, slide in enumerate(self.slides):
            if slide['type'] == SlideType.WEBVIEW:
                url = slide['data'].get('url')
                if url:
                    # Use a factory function to capture the variable properly
                    def load_webview_task(u=url):
                        self.webview_manager.load_url(u)
                    
                    # 800ms delay between heavy webview loads
                    self.task_queue.add_task(load_webview_task, f"Load Webview {i}", delay_ms=800)
        
        # 3. Fetch location (for timezone sync) and weather
        # Always fetch location at startup to sync timezone
        self.task_queue.add_task(self.fetch_location, "Fetch Location", delay_ms=1500)
        
        # Start the queue
        self.task_queue.start()

    def _restore_window_state(self):
        """Restore window state - ensure fullscreen is properly applied."""
        # Only re-apply fullscreen if somehow it was lost (safety net)
        if self.is_fullscreen and not self.isFullScreen():
            self.showFullScreen()
        if self.is_fullscreen:
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            self.activateWindow()

    def _on_brightness_changed(self, value: float):
        """Handle brightness change signal."""
        self._update_cached_colors()
        
        # Update software overlay if no system backlight
        if not self.brightness_manager.has_system_backlight:
            # value is 0.0-1.0, overlay opacity should be inverted
            # 1.0 brightness -> 0.0 opacity
            # 0.0 brightness -> 1.0 opacity
            # Note: BrightnessManager clamps min brightness to 0.05
            self.brightness_overlay.set_opacity(1.0 - value)
        else:
            self.brightness_overlay.hide()
            
        self.update()
        
        # Sync slider if needed (without signaling)
        if self.brightness_slider:
            self.brightness_slider.blockSignals(True)
            self.brightness_slider.setValue(int(value * 100))
            self.brightness_slider.blockSignals(False)
            
    def _on_auto_brightness_toggled(self, enabled: bool):
        """Handle auto-brightness toggle."""
        if self.auto_brightness_checkbox:
            self.auto_brightness_checkbox.blockSignals(True)
            self.auto_brightness_checkbox.setChecked(enabled)
            self.auto_brightness_checkbox.blockSignals(False)
            
        if self.brightness_slider:
            self.brightness_slider.setEnabled(not enabled)
            self.brightness_slider.update()

    def setup_digit_patterns(self):
        """Setup 3x5 digit patterns"""
        self.digit_patterns = {
            "0": [[1,1,1], [1,0,1], [1,0,1], [1,0,1], [1,1,1]],
            "1": [[0,1,0], [1,1,0], [0,1,0], [0,1,0], [1,1,1]],
            "2": [[1,1,1], [0,0,1], [1,1,1], [1,0,0], [1,1,1]],
            "3": [[1,1,1], [0,0,1], [1,1,1], [0,0,1], [1,1,1]],
            "4": [[1,0,1], [1,0,1], [1,1,1], [0,0,1], [0,0,1]],
            "5": [[1,1,1], [1,0,0], [1,1,1], [0,0,1], [1,1,1]],
            "6": [[1,1,1], [1,0,0], [1,1,1], [1,0,1], [1,1,1]],
            "7": [[1,1,1], [0,0,1], [0,0,1], [0,0,1], [0,0,1]],
            "8": [[1,1,1], [1,0,1], [1,1,1], [1,0,1], [1,1,1]],
            "9": [[1,1,1], [1,0,1], [1,1,1], [0,0,1], [1,1,1]],
        }

    def update_scale_factor(self):
        """Update scaling factor based on window size - optimized for 800x480"""
        width_scale = self.width() / self.base_width
        height_scale = self.height() / self.base_height
        raw_scale = min(width_scale, height_scale)

        # At 800x480, scale_factor = 1.0 (perfect)
        # Below 800x480, scale more conservatively to keep UI usable
        # Above 800x480, scale proportionally
        if raw_scale < 1.0:
            # For smaller screens, don't shrink as aggressively
            self.scale_factor = max(0.7, 0.7 + (raw_scale - 0.7) * 0.6)
        else:
            # For larger screens, scale normally
            self.scale_factor = raw_scale
        self._language_control_layout = None  # исправлено: принудительно пересчитываем геометрию кнопок при смене масштаба

    def get_scaled_font_size(self, base_size: int) -> int:
        """Get scaled font size based on current scale factor"""
        return max(int(base_size * 0.7), int(base_size * self.scale_factor))

    def get_ui_size(self, base_800x480: int, min_size: int = None) -> int:
        """Get size for UI elements optimized for 800x480"""
        if min_size is None:
            min_size = max(int(base_800x480 * 0.6), base_800x480 - 10)
        return max(min_size, int(base_800x480 * self.scale_factor))

    def get_spacing(self, base_800x480: int, min_spacing: int = None) -> int:
        """Get spacing optimized for 800x480"""
        if min_spacing is None:
            min_spacing = max(2, base_800x480 - 4)
        return max(min_spacing, int(base_800x480 * self.scale_factor))

    def calculate_display_parameters(self):
        """Calculate dot sizes based on window size with division by zero protection"""
        canvas_width = max(1, self.width())
        canvas_height = max(1, self.height())

        base_dot_size = 44
        base_dot_spacing = max(1, 50)  # Protect against zero
        base_inter_digit_spacing = 60

        ratio_dot = base_dot_size / base_dot_spacing
        ratio_inter = base_inter_digit_spacing / base_dot_spacing

        units_width = 4 * (2 + ratio_dot) + 3 * ratio_inter
        # Height units consider digits plus date spacing
        date_spacing_units = 3.0  # empirical spacing below digits for date text
        units_height = 5 + ratio_dot + date_spacing_units

        # Protect against division by zero
        units_width = max(1.0, units_width)
        units_height = max(1.0, units_height)

        s_by_width = canvas_width / units_width
        s_by_height = canvas_height / units_height
        base_s = min(s_by_width, s_by_height)
        s = max(4, int(base_s * 0.8))
        
        self.dot_spacing = s
        self.dot_size = max(4, int(ratio_dot * s))
        self.inter_digit_spacing = max(6, int(ratio_inter * s))

        self.digit_actual_width = 2 * self.dot_spacing + self.dot_size
        self.digit_actual_height = 4 * self.dot_spacing + self.dot_size
        self.colon_gap = max(self.inter_digit_spacing + self.dot_spacing // 2,
                             int(self.inter_digit_spacing * 1.7))
        self.clock_total_width = 4 * self.digit_actual_width + 2 * self.inter_digit_spacing + self.colon_gap
        self.clock_left_margin = max((canvas_width - self.clock_total_width) // 2, 0)
        adaptive_date_font = int(self.dot_size * 0.78 + canvas_height * 0.018)
        self._date_font_size = max(18, adaptive_date_font)
        self._date_gap = max(2, int(self.dot_spacing * 0.14))
        total_clock_date_height = self.digit_actual_height + self._date_gap + self._date_font_size
        self.clock_area_height = total_clock_date_height
        self.time_top_margin = max((canvas_height - total_clock_date_height) // 2, 0)
        self.time_start_y = self.time_top_margin + self.dot_size // 2
        self.colon_center_y = self.time_start_y + 2 * self.dot_spacing
        self._dot_pixmap_cache.clear()

    def _tr(self, key: str, **kwargs) -> str:
        lang_map = self.TRANSLATIONS.get(self.current_language)
        if lang_map is None:
            lang_map = self.TRANSLATIONS.get("EN", {})
        text = lang_map.get(key)
        if text is None:
            text = self.TRANSLATIONS.get("EN", {}).get(key, key)
        if kwargs:
            try:
                text = text.format(**kwargs)
            except Exception:
                pass
        return text

    def _update_widget_translation(self, widget, attr: str, key: str, fmt_kwargs: Optional[Dict[str, object]] = None):
        if widget is None:
            return
        fmt_kwargs = fmt_kwargs or {}
        text = self._tr(key, **fmt_kwargs)
        getattr(widget, attr)(text)

    def _register_i18n_widget(self, widget, key: str, attr: str = "setText", *, fmt_kwargs: Optional[Dict[str, object]] = None):
        if widget is None:
            return
        fmt = fmt_kwargs or {}
        entry = (widget, attr, fmt)
        self._i18n_widgets.setdefault(key, []).append(entry)
        self._update_widget_translation(widget, attr, key, fmt)

    def _clear_i18n_widgets(self):
        self._i18n_widgets.clear()

    def _apply_language(self):
        self.setWindowTitle(self._tr("window_title"))

        for key, entries in self._i18n_widgets.items():
            for widget, attr, fmt_kwargs in entries:
                if widget is not None:
                    self._update_widget_translation(widget, attr, key, fmt_kwargs)

        if self.card_edit_mode:
            self.update()

    def _create_settings_panel(self, title_key: str, *, width_ratio: float = 0.42,
                               height_ratio: float = 0.58) -> Tuple[QFrame, QVBoxLayout]:
        """Create and position a reusable settings panel with a title."""
        if self.edit_panel:
            self.edit_panel.deleteLater()

        self.edit_panel = AnimatedPanel(self)
        self.edit_panel.setObjectName("settingsPanel")
        self.edit_panel.setStyleSheet(
            f"""
            QFrame#settingsPanel {{
                background-color: rgba(15, 15, 15, 250);
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 16px;
            }}
            QLabel {{
                color: #f0f0f0;
                font-family: '{self.font_family}';
                margin: 0px;
                padding: 0px;
            }}
            QPushButton[buttonRole="primary"] {{
                background-color: #ffffff;
                color: #151515;
                border: none;
                border-radius: {self.get_ui_size(8, 6)}px;
                padding: {self.get_ui_size(8, 6)}px {self.get_ui_size(16, 12)}px;
                font-weight: 600;
                font-size: {self.get_ui_size(12, 10)}px;
                min-width: {self.get_ui_size(75, 60)}px;
                min-height: {self.get_ui_size(32, 26)}px;
                font-family: '{self.font_family}';
            }}
            QPushButton[buttonRole="secondary"] {{
                background-color: rgba(255, 255, 255, 15);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: {self.get_ui_size(8, 6)}px;
                padding: {self.get_ui_size(8, 6)}px {self.get_ui_size(16, 12)}px;
                color: #f0f0f0;
                font-weight: 500;
                font-size: {self.get_ui_size(12, 10)}px;
                min-width: {self.get_ui_size(75, 60)}px;
                min-height: {self.get_ui_size(32, 26)}px;
                font-family: '{self.font_family}';
            }}
            QCheckBox {{
                color: #f0f0f0;
                font-size: {self.get_ui_size(12, 10)}px;
                font-family: '{self.font_family}';
            }}
        """
        )

        layout = QVBoxLayout(self.edit_panel)
        # Optimized spacing and margins for 800x480
        spacing = self.get_spacing(12, 6)
        margins = self.get_spacing(20, 12)
        layout.setSpacing(spacing)
        layout.setContentsMargins(margins, int(margins * 0.8), margins, int(margins * 0.8))

        title_label = QLabel()
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_size = self.get_ui_size(14, 12)
        title_label.setStyleSheet(f"font-size: {title_size}px; font-weight: 700; font-family: '{self.font_family}';")
        self._register_i18n_widget(title_label, title_key)
        layout.addWidget(title_label)
        layout.addSpacing(self.get_spacing(6, 3))

        self._edit_panel_ratios = (max(0.2, min(width_ratio, 0.9)),
                                   max(0.2, min(height_ratio, 0.9)))
        self._apply_settings_panel_geometry()

        # Setup and start panel animation
        self.edit_panel.set_opacity(0.0)
        self.edit_panel.set_scale(0.8)
        self.edit_panel.show()

        self._animate_panel_in()

        return self.edit_panel, layout

    def _settings_section_label(self, key: str) -> QLabel:
        """Create a styled section label bound to translations."""
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        label.setWordWrap(False)
        font_size = self.get_ui_size(11, 10)
        fixed_height = self.get_ui_size(int(font_size * 1.3), 14)
        label.setStyleSheet(f"""
            QLabel {{
                font-size: {font_size}px;
                font-weight: 600;
                color: #f0f0f0;
                font-family: '{self.font_family}';
                margin: 0px;
                padding: 0px;
                border: none;
                background: transparent;
            }}
        """)
        label.setFixedHeight(fixed_height)
        label.setMinimumHeight(fixed_height)
        label.setMaximumHeight(fixed_height)
        label.setContentsMargins(0, 0, 0, 0)
        from PyQt6.QtWidgets import QSizePolicy
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._register_i18n_widget(label, key)
        return label

    def _add_centered_widget(self, layout: QVBoxLayout, widget: QWidget):
        """Center a widget horizontally within the given layout."""
        row = QHBoxLayout()
        row.setSpacing(0)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch()
        row.addWidget(widget)
        row.addStretch()
        layout.addLayout(row)

    def _apply_settings_panel_geometry(self):
        """Apply geometry to current settings panel based on window size."""
        if not self.edit_panel:
            return

        width_ratio, height_ratio = self._edit_panel_ratios or (0.42, 0.58)
        # Use smaller minimum sizes for small screens
        min_width = 280 if self.width() < 600 else 400
        min_height = 250 if self.height() < 700 else 350

        panel_width = max(min_width, int(self.width() * width_ratio))
        panel_height = max(min_height, int(self.height() * height_ratio))

        x = (self.width() - panel_width) // 2
        y = (self.height() - panel_height) // 2
        self.edit_panel.setGeometry(x, y, panel_width, panel_height)

    def _cleanup_panel_animations(self):
        """Clean up existing panel animations to prevent memory leaks"""
        if hasattr(self, 'panel_opacity_animation') and self.panel_opacity_animation:
            if self.panel_opacity_animation.state() == QPropertyAnimation.State.Running:
                # Set current value before stopping to prevent jump
                if self.edit_panel:
                    current_opacity = self.panel_opacity_animation.currentValue()
                    self.panel_opacity_animation.stop()
                    if current_opacity is not None:
                        self.edit_panel.set_opacity(float(current_opacity))
                else:
                    self.panel_opacity_animation.stop()
            self.panel_opacity_animation.deleteLater()
            self.panel_opacity_animation = None

        if hasattr(self, 'panel_scale_animation') and self.panel_scale_animation:
            if self.panel_scale_animation.state() == QPropertyAnimation.State.Running:
                # Set current value before stopping to prevent jump
                if self.edit_panel:
                    current_scale = self.panel_scale_animation.currentValue()
                    self.panel_scale_animation.stop()
                    if current_scale is not None:
                        self.edit_panel.set_scale(float(current_scale))
                else:
                    self.panel_scale_animation.stop()
            self.panel_scale_animation.deleteLater()
            self.panel_scale_animation = None

    def _animate_panel_in(self):
        """Animate panel appearance"""
        if not self.edit_panel:
            return

        # Clean up existing animations and get current values
        current_opacity = 0.0
        current_scale = 0.8

        if self.panel_opacity_animation and self.panel_opacity_animation.state() == QPropertyAnimation.State.Running:
            current_opacity = self.panel_opacity_animation.currentValue() or 0.0
        else:
            current_opacity = self.edit_panel.get_opacity()

        if self.panel_scale_animation and self.panel_scale_animation.state() == QPropertyAnimation.State.Running:
            current_scale = self.panel_scale_animation.currentValue() or 0.8
        else:
            current_scale = self.edit_panel.get_scale()

        self._cleanup_panel_animations()

        # Opacity animation
        self.panel_opacity_animation = QPropertyAnimation(self.edit_panel, b"opacity")
        self.panel_opacity_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.panel_opacity_animation.setDuration(400)
        self.panel_opacity_animation.setStartValue(float(current_opacity))
        self.panel_opacity_animation.setEndValue(1.0)

        # Scale animation
        self.panel_scale_animation = QPropertyAnimation(self.edit_panel, b"scale")
        self.panel_scale_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.panel_scale_animation.setDuration(500)
        self.panel_scale_animation.setStartValue(float(current_scale))
        self.panel_scale_animation.setEndValue(1.0)

        self.panel_opacity_animation.start()
        self.panel_scale_animation.start()

    def _animate_panel_out(self, callback=None):
        """Animate panel disappearance"""
        if not self.edit_panel:
            if callback:
                callback()
            return

        # Get current values before cleanup
        current_opacity = 1.0
        current_scale = 1.0

        if self.panel_opacity_animation and self.panel_opacity_animation.state() == QPropertyAnimation.State.Running:
            current_opacity = self.panel_opacity_animation.currentValue() or 1.0
        else:
            current_opacity = self.edit_panel.get_opacity()

        if self.panel_scale_animation and self.panel_scale_animation.state() == QPropertyAnimation.State.Running:
            current_scale = self.panel_scale_animation.currentValue() or 1.0
        else:
            current_scale = self.edit_panel.get_scale()

        # Clean up existing animations
        self._cleanup_panel_animations()

        # Opacity animation
        self.panel_opacity_animation = QPropertyAnimation(self.edit_panel, b"opacity")
        self.panel_opacity_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.panel_opacity_animation.setDuration(300)
        self.panel_opacity_animation.setStartValue(float(current_opacity))
        self.panel_opacity_animation.setEndValue(0.0)

        # Scale animation
        self.panel_scale_animation = QPropertyAnimation(self.edit_panel, b"scale")
        self.panel_scale_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.panel_scale_animation.setDuration(300)
        self.panel_scale_animation.setStartValue(float(current_scale))
        self.panel_scale_animation.setEndValue(0.8)

        if callback:
            self.panel_opacity_animation.finished.connect(callback)

        self.panel_opacity_animation.start()
        self.panel_scale_animation.start()

    def get_nav_opacity(self) -> float:
        """Return current navigation opacity."""
        return self._nav_opacity

    def set_nav_opacity(self, value: float):
        """Set navigation opacity and trigger repaint."""
        value = max(0.0, min(1.0, float(value)))
        if math.isclose(self._nav_opacity, value, abs_tol=0.001):
            return
        self._nav_opacity = value
        self.update()

    navOpacity = pyqtProperty(float, fget=get_nav_opacity, fset=set_nav_opacity)

    def reset_navigation_timer(self):
        """Reset the navigation inactivity timer"""
        if not self.edit_mode:
            self.show_navigation()
            self.nav_hide_timer.start(10000)
            # Also reset the clock return timer if we're not on the clock slide
            self.reset_clock_return_timer()

    def _ensure_slide_order(self):
        """Ensure CLOCK is always first and ADD is always last"""
        if not self.slides:
            return
        
        # Find CLOCK and ADD slides
        clock_slide = None
        add_slide = None
        other_slides = []
        
        for slide in self.slides:
            if slide.get('type') == SlideType.CLOCK:
                clock_slide = slide
            elif slide.get('type') == SlideType.ADD:
                add_slide = slide
            else:
                other_slides.append(slide)
        
        # Rebuild slides list: CLOCK first, others in middle, ADD last
        self.slides = []
        if clock_slide:
            self.slides.append(clock_slide)
        self.slides.extend(other_slides)
        if add_slide:
            self.slides.append(add_slide)
    
    def reset_clock_return_timer(self):
        """Reset the timer that returns to clock slide after inactivity"""
        # Only start timer if we're not on clock slide and not in edit mode
        if not self.edit_mode and self.current_slide > 0:
            # Find the clock slide (should be at index 0)
            has_clock = any(slide["type"] == SlideType.CLOCK for slide in self.slides)
            if has_clock:
                self.clock_return_timer.start(self.INACTIVITY_TIMEOUT)
        else:
            self.clock_return_timer.stop()

    def return_to_clock(self):
        """Return to clock slide after inactivity timeout"""
        if not self.edit_mode and self.current_slide > 0:
            # Find the clock slide (should be at index 0)
            clock_index = next((i for i, slide in enumerate(self.slides) 
                              if slide["type"] == SlideType.CLOCK), -1)
            if clock_index >= 0:
                self.current_slide = clock_index
                self.animate_to_current_slide()
                self.update()
                self.update_active_webviews()

    def show_navigation(self):
        """Show navigation dots"""
        self.nav_hidden = False
        if self.nav_opacity_animation.state() == QPropertyAnimation.State.Running:
            self.nav_opacity_animation.stop()
        self.nav_opacity_animation.setStartValue(self._nav_opacity)
        self.nav_opacity_animation.setEndValue(1.0)
        self.nav_opacity_animation.start()
        self.update()

    def hide_navigation(self):
        """Hide navigation dots"""
        if self.edit_mode:
            return
        if self.nav_hidden and math.isclose(self._nav_opacity, 0.0, abs_tol=0.001):
            return
        self.nav_hidden = True
        if self.nav_opacity_animation.state() == QPropertyAnimation.State.Running:
            self.nav_opacity_animation.stop()
        self.nav_opacity_animation.setStartValue(self._nav_opacity)
        self.nav_opacity_animation.setEndValue(0.0)
        self.nav_opacity_animation.start()
        self.update()

    def fetch_location(self):
        """Fetch location from IP geolocation API (HTTPS)"""
        if self.location_loading:
            return

        self.location_loading = True
        # Using ipapi.co with HTTPS for secure geolocation
        url = "https://ipapi.co/json/"
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Mozilla/5.0")
        reply = self.network_manager.get(request)
        reply.finished.connect(lambda: self.handle_location_response(reply))

    def _cleanup_parser_thread(self, thread_attr: str):
        """Safely cleanup a JSON parser thread to prevent memory leaks."""
        old_thread = getattr(self, thread_attr, None)
        if not old_thread:
            return

        setattr(self, thread_attr, None)

        # Disconnect signals to prevent callbacks after deletion
        try:
            old_thread.finished.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            old_thread.error.disconnect()
        except (RuntimeError, TypeError):
            pass

        # Stop thread if running
        if old_thread.isRunning():
            old_thread.quit()
            old_thread.wait(100)  # Short timeout

        # Schedule deletion
        old_thread.deleteLater()

    def handle_location_response(self, reply: QNetworkReply):
        """Handle location API response"""
        try:
            self.location_loading = False

            if reply.error() == QNetworkReply.NetworkError.NoError:
                try:
                    response_data = bytes(reply.readAll()).decode()

                    # Clean up old location parser thread
                    self._cleanup_parser_thread('location_parser_thread')

                    # Create new parser thread
                    self.location_parser_thread = JsonParserThread(response_data, 'location')
                    self.location_parser_thread.finished.connect(self._on_location_parsed)
                    self.location_parser_thread.error.connect(self._on_json_parse_error)
                    self.location_parser_thread.start()

                except Exception as e:
                    self.weather_status_message = f"Location error: {str(e)}"
            else:
                self.weather_status_message = f"Location failed: {reply.errorString()}"
        finally:
            reply.deleteLater()

    def _on_location_parsed(self, data: dict, data_type: str):
        """Handle parsed location data"""
        if data_type != 'location':
            return

        # ipapi.co uses 'latitude' and 'longitude' keys
        self.location_lat = data.get('latitude')
        self.location_lon = data.get('longitude')
        self.location_city = data.get('city', '')
        timezone = data.get('timezone')

        if self.location_lat and self.location_lon:
            # Set system timezone if available
            if timezone:
                self._set_system_timezone(timezone)
            # Save to settings
            self.save_settings()
            # Fetch weather with new location
            self.fetch_weather()
        else:
            self.weather_status_message = "Location unavailable"
    
    def _set_system_timezone(self, timezone: str):
        """Set system timezone based on location"""
        import subprocess
        try:
            # Check if timezone is valid
            result = subprocess.run(
                ['timedatectl', 'list-timezones'],
                capture_output=True, text=True, timeout=5
            )
            valid_timezones = result.stdout.strip().split('\n')
            
            if timezone in valid_timezones:
                # Get current timezone
                current = subprocess.run(
                    ['timedatectl', 'show', '--property=Timezone', '--value'],
                    capture_output=True, text=True, timeout=5
                )
                current_tz = current.stdout.strip()
                
                # Only set if different
                if current_tz != timezone:
                    subprocess.run(
                        ['sudo', 'timedatectl', 'set-timezone', timezone],
                        capture_output=True, timeout=10
                    )
                    logging.info(f"Timezone set to {timezone}")
        except Exception as e:
            logging.warning(f"Failed to set timezone: {e}")

    def fetch_weather(self):
        """Fetch weather data from API"""
        if self.weather_loading:
            return

        # If no location yet, fetch it first
        if self.location_lat is None or self.location_lon is None:
            if not self.location_loading:
                self.fetch_location()
            return

        lat, lon = self.location_lat, self.location_lon

        params = {
            'latitude': lat,
            'longitude': lon,
            'current': 'temperature_2m,weather_code,wind_speed_10m,is_day',
            'timezone': 'auto'
        }

        url = f"https://api.open-meteo.com/v1/forecast?{urlencode(params)}"
        request = QNetworkRequest(QUrl(url))

        self.weather_loading = True
        reply = self.network_manager.get(request)
        reply.finished.connect(lambda: self.handle_weather_response(reply))

    def handle_weather_response(self, reply: QNetworkReply):
        """Handle weather API response"""
        try:
            # Don't set loading=False yet, wait for parser
            if reply.error() == QNetworkReply.NetworkError.NoError:
                try:
                    response_data = bytes(reply.readAll()).decode()

                    # Clean up old weather parser thread
                    self._cleanup_parser_thread('weather_parser_thread')

                    # Create new parser thread
                    self.weather_parser_thread = JsonParserThread(response_data, 'weather')
                    self.weather_parser_thread.finished.connect(self._on_weather_parsed)
                    self.weather_parser_thread.error.connect(self._on_json_parse_error)
                    self.weather_parser_thread.start()
                    
                    # Loading continues in thread...
                    return 

                except Exception as e:
                    self.weather_loading = False
                    self.weather_status_message = f"Weather error: {str(e)}"
                    self.update()
            else:
                self.weather_loading = False
                self.weather_status_message = f"Weather failed: {reply.errorString()}"
                self.update()
        finally:
            reply.deleteLater()

    def _on_weather_parsed(self, data: dict, data_type: str):
        """Handle parsed weather data"""
        if data_type != 'weather':
            return

        self.weather_loading = False  # Parsing finished
        
        current = data.get('current', {})

        temp = current.get('temperature_2m', 0)
        code = current.get('weather_code', 0)
        wind_kmh = current.get('wind_speed_10m', 0)
        is_day = current.get('is_day', 1)

        self.weather_data = {
            'temp': round(temp),
            'code': int(code) if code is not None else 0,
            'wind': wind_kmh / 3.6,  # km/h to m/s
            'is_day': int(is_day) if is_day is not None else 1
        }
        self.weather_status_message = ""  # Clear any error messages
        self.update()

    def _on_json_parse_error(self, error_message: str, data_type: str):
        """Handle JSON parse errors"""
        if data_type == 'location':
            self.location_loading = False
            self.weather_status_message = f"Location parse error: {error_message}"
        elif data_type == 'weather':
            self.weather_loading = False
            self.weather_status_message = f"Weather parse error: {error_message}"
            self.update()

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Reset clock return timer on user interaction
            self.reset_clock_return_timer()
            self.press_start_pos = event.pos()  # исправлено: обновляем стартовую позицию до обработки контролов
            self._skip_release_processing = False
            
            if self.card_edit_mode:
                self.exit_card_edit_mode()
            elif self.edit_mode:
                # In edit mode, check for fullscreen button clicks first
                if self.check_fullscreen_button_click(event.pos()):
                    return
                # Then check language button clicks
                if self.check_language_button_click(event.pos()):
                    return

                # Check if clicking on a card to potentially start reordering
                card_index = self.get_card_at_position(event.pos())
                if card_index is not None and card_index < len(self.slides):
                    slide_type = self.slides[card_index].get('type')
                    # Clock (always first) and Add (always last) cards cannot be reordered
                    if slide_type not in (SlideType.CLOCK, SlideType.ADD):
                        # Start timer for reordering activation (1.5 second hold - less sensitive)
                        self.reorder_pending_index = card_index
                        self.press_start_pos = event.pos()
                        self.mouse_pressed = True
                        self.reorder_activation_timer.start(1500)
                        return

                # Otherwise start drag detection
                self.mouse_pressed = True
                self.press_start_pos = event.pos()
                self.drag_start_x = event.pos().x()
                self.is_dragging = False
            else:
                # Normal mode - start long press detection
                self.mouse_pressed = True
                self.press_start_pos = event.pos()
                self.press_start_time = datetime.now().timestamp()
                self.drag_start_x = event.pos().x()
                self.is_dragging = False
                self.long_press_timer.start(800)

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move for dragging with smooth interpolation"""
        if self.mouse_pressed:
            # Handle card reordering in edit mode
            if self.is_reordering_card and self.reorder_drag_index is not None:
                delta = QPointF(event.pos() - self.press_start_pos)
                
                # Limit drag offset to prevent card from flying too far
                # Card can only move between position 1 and len-2 (not to CLOCK or ADD positions)
                card_width = self.width()
                drag_idx = self.reorder_drag_index
                
                # Calculate allowed range (positions 1 to len-2)
                min_allowed_idx = 1
                max_allowed_idx = len(self.slides) - 2
                
                # Max offset left: can't go past position 1
                max_left = -(drag_idx - min_allowed_idx) * card_width - card_width * 0.3
                # Max offset right: can't go past position len-2
                max_right = (max_allowed_idx - drag_idx) * card_width + card_width * 0.3
                
                # Clamp the delta with rubber band effect at edges
                clamped_x = delta.x()
                if clamped_x < max_left:
                    # Rubber band effect - resistance when pulling past limit
                    overshoot = max_left - clamped_x
                    clamped_x = max_left - overshoot * 0.2
                elif clamped_x > max_right:
                    overshoot = clamped_x - max_right
                    clamped_x = max_right + overshoot * 0.2
                
                self.reorder_drag_offset = QPointF(clamped_x, delta.y() * 0.3)  # Also limit vertical movement
                self._update_reorder_auto_scroll(event.pos())

                # Check if we should swap with another card
                new_target = self.get_card_at_position(event.pos())
                if new_target is not None and new_target != self.reorder_target_index:
                    # Don't allow swapping with CLOCK (index 0) or ADD (last index) cards
                    target_type = self.slides[new_target].get('type') if new_target < len(self.slides) else None
                    # Also prevent moving to position 0 (reserved for CLOCK) or last position (reserved for ADD)
                    is_reserved_position = (new_target == 0 or new_target == len(self.slides) - 1)
                    if target_type not in (SlideType.CLOCK, SlideType.ADD) and not is_reserved_position:
                        self.reorder_target_index = new_target
                        self.animate_card_reordering()

                self.update()
                return

            delta_x = event.pos().x() - self.press_start_pos.x()
            delta_y = abs(event.pos().y() - self.press_start_pos.y())

            # If moved while waiting for reorder activation, cancel it and allow swipe
            # Increased threshold to 15px to be less sensitive
            if self.reorder_activation_timer.isActive() and (abs(delta_x) > 15 or delta_y > 15):
                self.reorder_activation_timer.stop()
                self.reorder_pending_index = None

            # Detect horizontal swipe (more horizontal than vertical)
            if abs(delta_x) > 5 and abs(delta_x) > delta_y * 2:
                if not self.is_dragging:
                    self.is_dragging = True
                    self.long_press_timer.stop()
                    self.reorder_activation_timer.stop()
                    # Initialize smoothed offset on first drag
                    self._smoothed_offset = -self.current_slide * self.width()
                    self._drag_velocity_history.clear()

                # Apply real-time drag offset with exponential smoothing
                if not self.edit_mode and len(self.slides) > 1:
                    base_offset = -self.current_slide * self.width()
                    drag_factor = 0.6  # Resistance factor
                    raw_offset = base_offset + delta_x * drag_factor

                    # Apply bounds to prevent dragging too far
                    max_offset = 0
                    min_offset = -(len(self.slides) - 1) * self.width()
                    raw_offset = max(min_offset, min(max_offset, raw_offset))

                    # Fix: Exponential smoothing for stable swipes (prevents jitter)
                    # Formula: smoothed = alpha * raw + (1 - alpha) * previous_smoothed
                    self._smoothed_offset = (
                        self._drag_smoothing_alpha * raw_offset +
                        (1 - self._drag_smoothing_alpha) * self._smoothed_offset
                    )

                    self.drag_current_offset = self._smoothed_offset

                    # Fix: Track velocity history for smooth release prediction
                    current_time = datetime.now().timestamp()
                    self._drag_velocity_history.append((current_time, delta_x))
                    if len(self._drag_velocity_history) > self._drag_velocity_history_size:
                        self._drag_velocity_history.pop(0)

                    # Update slide container directly for immediate feedback
                    if self.slide_container:
                        self.slide_container.set_offset_x(self.drag_current_offset)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._skip_release_processing:
                self._skip_release_processing = False  # исправлено: не обрабатываем свайп после клика по контролам
                self.mouse_pressed = False
                self.is_dragging = False
                self.drag_current_offset = 0.0
                return

            self.long_press_timer.stop()
            self.reorder_activation_timer.stop()

            # Handle card reordering completion
            if self.is_reordering_card and self.reorder_drag_index is not None:
                self._stop_reorder_auto_scroll()
                self._last_reorder_cursor_pos = None
                # Finalize the swap
                if self.reorder_target_index != self.reorder_drag_index:
                    # Verify target is valid (not CLOCK position 0, not ADD position last)
                    target_valid = (
                        self.reorder_target_index > 0 and 
                        self.reorder_target_index < len(self.slides) - 1
                    )
                    
                    if target_valid:
                        # Actually swap the slides in the array
                        self.slides[self.reorder_drag_index], self.slides[self.reorder_target_index] = \
                            self.slides[self.reorder_target_index], self.slides[self.reorder_drag_index]

                        # Update current_slide if we swapped the active card
                        if self.current_slide == self.reorder_drag_index:
                            self.current_slide = self.reorder_target_index
                        elif self.current_slide == self.reorder_target_index:
                            self.current_slide = self.reorder_drag_index

                        # Ensure CLOCK stays first and ADD stays last
                        self._ensure_slide_order()
                        self.save_settings()

                # Reset reordering state
                self.is_reordering_card = False
                self.reorder_drag_index = None
                self.reorder_target_index = None
                self.reorder_drag_offset = QPointF()
                self.mouse_pressed = False

                # Clear any remaining animations
                self.finish_all_card_animations()

                self.update()
                return

            # Calculate total movement
            delta_x = event.pos().x() - self.press_start_pos.x()
            total_move = abs(delta_x)

            # If was dragging, handle smooth release
            if self.is_dragging and not self.edit_mode:
                # Fix: Reset drag offset to prevent visual glitches
                self.drag_current_offset = 0.0

                # Fix: Calculate velocity from history for better prediction
                calculated_velocity = 0.0
                if len(self._drag_velocity_history) >= 2:
                    first_time, first_pos = self._drag_velocity_history[0]
                    last_time, last_pos = self._drag_velocity_history[-1]
                    time_diff = last_time - first_time
                    if time_diff > 0:
                        # pixels per second
                        calculated_velocity = abs((last_pos - first_pos) / time_diff)

                # Determine if we should snap to next/previous slide
                # Use calculated velocity for more accurate detection
                velocity_threshold = 300  # pixels per second (was 80 static pixels)
                position_threshold = self.width() * 0.25  # 25% of screen width

                should_change_slide = (calculated_velocity > velocity_threshold or
                                     abs(delta_x) > position_threshold)

                if should_change_slide:
                    if delta_x < 0:  # Swiped left
                        self.next_slide(calculated_velocity)
                    else:  # Swiped right
                        self.previous_slide(calculated_velocity)
                else:
                    # Snap back to current slide
                    self.animate_to_current_slide()
            elif total_move > 30:
                # Fallback for non-dragging swipes
                if delta_x < -30:
                    self.next_slide()
                elif delta_x > 30:
                    self.previous_slide()
            else:
                # No significant movement - treat as click
                if self.edit_mode:
                    # First check fullscreen button (highest priority)
                    if self.check_fullscreen_button_click(event.pos()):
                        pass  # Fullscreen button handled
                    # Then check language buttons
                    elif self.check_language_button_click(event.pos()):
                        pass  # Language button handled
                    # Then check if clicked on the card itself
                    elif (not self._edit_transition_active and
                          self.check_card_click(event.pos())):
                        pass  # Card editor opened
                    else:
                        # Clicked outside everything - exit edit mode when animations idle
                        if not self._edit_transition_active:
                            self.exit_edit_mode()
                else:
                    if self.is_click_on_current_card(event.pos()):
                        slide = self.slides[self.current_slide]
                        if slide['type'] == SlideType.ADD:
                            self.show_add_menu()
            
            self.mouse_pressed = False
            self.is_dragging = False
            self.drag_current_offset = 0.0
            
            # Update webview geometry after swipe completes
            self.update_webview_geometry()

    def on_long_press(self):
        """Handle long press to enter edit mode"""
        if not self.edit_mode and not self._edit_transition_active:
            self.enter_edit_mode()

    def _activate_card_reordering(self):
        """Activate card reordering after 1 second hold"""
        if self.reorder_pending_index is not None and self.mouse_pressed:
            self.is_reordering_card = True
            self.reorder_drag_index = self.reorder_pending_index
            self.reorder_target_index = self.reorder_pending_index
            self.reorder_drag_offset = QPointF()
            self.reorder_pending_index = None
            self._last_reorder_cursor_pos = QPoint(self.press_start_pos)
            self.update()

    def _stop_reorder_auto_scroll(self):
        """Stop auto scrolling while reordering cards."""
        if self.reorder_auto_scroll_timer.isActive():
            self.reorder_auto_scroll_timer.stop()
        self.reorder_auto_scroll_direction = 0

    def _update_reorder_auto_scroll(self, cursor_pos: QPoint):
        """Check cursor position and start/stop auto-scroll near edges."""
        if not self.is_reordering_card:
            self._stop_reorder_auto_scroll()
            return

        self._last_reorder_cursor_pos = QPoint(cursor_pos)

        if len(self.slides) <= 1:
            self._stop_reorder_auto_scroll()
            return

        width = max(1, self.width())
        threshold = max(30, int(width * 0.12))
        direction = 0

        if cursor_pos.x() < threshold and self.current_slide > 0:
            direction = -1
        elif cursor_pos.x() > width - threshold and self.current_slide < len(self.slides) - 1:
            direction = 1

        if direction != 0:
            if self.reorder_auto_scroll_direction != direction:
                self.reorder_auto_scroll_direction = direction
                self.reorder_auto_scroll_timer.start()
            elif not self.reorder_auto_scroll_timer.isActive():
                self.reorder_auto_scroll_timer.start()
        else:
            self._stop_reorder_auto_scroll()

    def _perform_reorder_auto_scroll(self):
        """Move slide strip when dragging card near edges."""
        if not self.is_reordering_card or self.reorder_auto_scroll_direction == 0:
            self._stop_reorder_auto_scroll()
            return

        direction = self.reorder_auto_scroll_direction
        next_slide = self.current_slide + direction

        if next_slide < 0 or next_slide >= len(self.slides):
            self._stop_reorder_auto_scroll()
            return

        width = max(1, self.width())

        if hasattr(self, 'offset_animation') and self.offset_animation and self.offset_animation.state() == QPropertyAnimation.State.Running:
            self._finalize_offset_animation()

        previous_offset = self.slide_container.get_offset_x() if self.slide_container else 0.0
        target_offset = -next_slide * width

        if self.slide_container:
            self.slide_container.set_offset_x(target_offset)

        self.current_slide = next_slide

        offset_delta = target_offset - previous_offset
        if offset_delta != 0.0:
            self.reorder_drag_offset = QPointF(
                self.reorder_drag_offset.x() - offset_delta,
                self.reorder_drag_offset.y()
            )
            self.press_start_pos = QPoint(
                int(self.press_start_pos.x() + offset_delta),
                self.press_start_pos.y()
            )

        if self._last_reorder_cursor_pos is not None:
            new_target = self.get_card_at_position(self._last_reorder_cursor_pos)
            if new_target is not None and new_target != self.reorder_target_index:
                self.reorder_target_index = new_target
                self.animate_card_reordering()

        self.update()

    def get_card_at_position(self, pos: QPoint) -> Optional[int]:
        """Get the index of the card at the given screen position in edit mode"""
        if not self.edit_mode or not self.slides:
            return None

        card_scale = 0.62
        card_width = int(self.width() * card_scale)
        card_height = int(self.height() * card_scale)
        start_y = max(60, int(80 * self.scale_factor))
        center_x = self.width() // 2

        width = max(1, self.width())

        # First check if Y position is in valid range (with expanded touch area)
        touch_padding_y = int(card_height * 0.15)  # 15% padding for easier touch
        if not (start_y - touch_padding_y <= pos.y() <= start_y + card_height + touch_padding_y):
            return None

        # Find the closest card by X position (eliminates dead zones between cards)
        closest_idx = None
        min_distance = float('inf')

        for idx in range(len(self.slides)):
            # Calculate card position with any swap animations applied
            displacement = idx * width + self.slide_container.offset_x

            # Apply any active swap animation offset
            if idx in self.reorder_card_offsets:
                displacement += self.reorder_card_offsets[idx].x()

            card_x = (center_x - card_width // 2) + displacement
            card_center_x = card_x + card_width // 2

            # Calculate horizontal distance from touch point to card center
            distance = abs(pos.x() - card_center_x)

            # Update closest card if this one is closer
            if distance < min_distance:
                min_distance = distance
                closest_idx = idx

        # Return closest card if it's within reasonable range (within screen width)
        # This ensures we catch touches between cards while not selecting cards too far away
        if closest_idx is not None and min_distance < width:
            return closest_idx

        return None

    def animate_card_reordering(self):
        """
        Animate all cards to their correct positions during reordering.
        исправлено: анимирует все карточки между drag_index и target_index,
        возвращая остальные на свои места
        """
        if self.reorder_drag_index is None or self.reorder_target_index is None:
            return

        drag_idx = self.reorder_drag_index
        target_idx = self.reorder_target_index
        width = self.width()

        # Create animation object with custom property
        from PyQt6.QtCore import QObject, pyqtProperty

        class CardOffsetAnimator(QObject):
            def __init__(self, parent, card_index, target_offset):
                super().__init__(parent)
                self._offset_x = self.parent().reorder_card_offsets.get(card_index, QPointF()).x()
                self.card_index = card_index
                self.target_offset = target_offset

            def get_offset_x(self):
                return self._offset_x

            def set_offset_x(self, value):
                self._offset_x = value
                parent = self.parent()
                parent.reorder_card_offsets[self.card_index] = QPointF(value, 0)
                parent.update()

            offset_x = pyqtProperty(float, get_offset_x, set_offset_x)

        # Анимируем все карточки к правильным позициям
        for idx in range(len(self.slides)):
            # Пропускаем перетаскиваемую карточку - она управляется reorder_drag_offset
            if idx == drag_idx:
                continue
            
            # CLOCK (index 0) и ADD (last index) никогда не двигаются
            # Проверяем и по типу и по позиции
            if idx == 0 or idx == len(self.slides) - 1:
                continue
            slide_type = self.slides[idx].get('type') if idx < len(self.slides) else None
            if slide_type in (SlideType.CLOCK, SlideType.ADD):
                continue

            # Определяем целевое смещение для каждой карточки
            target_offset = 0.0

            if drag_idx < target_idx:
                # Перетаскиваем вправо: карточки между drag и target сдвигаются влево
                if drag_idx < idx <= target_idx:
                    target_offset = -width
            else:
                # Перетаскиваем влево: карточки между target и drag сдвигаются вправо
                if target_idx <= idx < drag_idx:
                    target_offset = width

            # Инициализируем offset если его нет
            if idx not in self.reorder_card_offsets:
                self.reorder_card_offsets[idx] = QPointF(0, 0)

            current_offset = self.reorder_card_offsets[idx].x()

            # Если смещение изменилось - создаём анимацию
            if abs(current_offset - target_offset) > 0.1:
                # Останавливаем старую анимацию для этого индекса
                if idx in self.reorder_swap_animations:
                    old_anim = self.reorder_swap_animations[idx]
                    if old_anim.state() == QPropertyAnimation.State.Running:
                        old_anim.stop()
                    old_anim.deleteLater()
                    del self.reorder_swap_animations[idx]

                # Создаём новую анимацию
                animator = CardOffsetAnimator(self, idx, target_offset)
                animation = QPropertyAnimation(animator, b"offset_x")
                animation.setDuration(250)
                animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
                animation.setStartValue(current_offset)
                animation.setEndValue(target_offset)
                animation.start()

                self.reorder_swap_animations[idx] = animation

    def finish_all_card_animations(self):
        """Stop and clean up all card reordering animations"""
        for anim in list(self.reorder_swap_animations.values()):
            if anim.state() == QPropertyAnimation.State.Running:
                anim.stop()
            anim.deleteLater()

        self.reorder_swap_animations.clear()
        self.reorder_card_offsets.clear()
        self._stop_reorder_auto_scroll()

    def _prepare_control_click(self, pos: QPoint):
        """Reset swipe state when tapping bottom controls"""
        self._skip_release_processing = True  # исправлено: не допускаем ложного свайпа после клика
        self.mouse_pressed = False
        self.is_dragging = False
        self.press_start_pos = QPoint(pos)
        self._drag_velocity_history.clear()
        self.long_press_timer.stop()
        self.reorder_activation_timer.stop()

    def _compute_language_control_layout(self):
        """Calculate rectangles for language/update/autostart buttons."""
        button_height = self.get_ui_size(28, 20)
        button_width = self.get_ui_size(60, 44)
        lang_spacing = self.get_spacing(12, 8)
        bottom_offset = self.get_spacing(34, 24)
        lang_y = self.height() - bottom_offset

        languages = ["RU", "EN", "UA"]
        total_width = len(languages) * button_width + (len(languages) - 1) * lang_spacing
        start_x = max(0, (self.width() - total_width) // 2)
        language_rects = []
        for index, lang in enumerate(languages):
            x = start_x + index * (button_width + lang_spacing)
            language_rects.append((lang, QRect(x, lang_y, button_width, button_height)))

        pill_width = self.get_ui_size(120, 92)
        wifi_width = self.get_ui_size(70, 54)
        margin_side = self.get_spacing(20, 14)
        autostart_rect = QRect(margin_side, lang_y, pill_width, button_height)
        wifi_rect = QRect(margin_side + pill_width + lang_spacing, lang_y, wifi_width, button_height)
        update_rect = QRect(self.width() - pill_width - margin_side, lang_y, pill_width, button_height)

        layout = {
            "language_rects": language_rects,
            "autostart_rect": autostart_rect,
            "wifi_rect": wifi_rect,
            "update_rect": update_rect,
            "button_height": button_height,
            "baseline_y": lang_y,
        }
        self._language_control_layout = layout
        return layout

    def check_language_button_click(self, pos: QPoint) -> bool:
        """Check if language button, update button, or autostart button was clicked"""
        if not self.edit_mode:
            return False

        layout = self._language_control_layout or self._compute_language_control_layout()

        autostart_rect = layout["autostart_rect"]
        if autostart_rect.contains(pos):
            self._prepare_control_click(pos)
            self.toggle_autostart()
            return True

        wifi_rect = layout["wifi_rect"]
        if wifi_rect.contains(pos):
            self._prepare_control_click(pos)
            self.open_wifi_settings()
            return True

        update_rect = layout["update_rect"]
        if update_rect.contains(pos):
            self._prepare_control_click(pos)
            self.show_notification("Checking for updates...", duration=2000, notification_type="info")
            self.update_checker.check_for_updates(silent=False)
            return True

        for lang, rect in layout["language_rects"]:
            if rect.contains(pos):
                if self.current_language != lang:
                    self.current_language = lang
                    self._apply_language()
                    self.save_settings()
                    self.update()
                self._prepare_control_click(pos)
                return True

        return False

    def check_fullscreen_button_click(self, pos: QPoint) -> bool:
        """Check if fullscreen button was clicked"""
        if not self.edit_mode:
            return False

        button_size = int(40 * self.scale_factor)
        button_margin = int(20 * self.scale_factor)
        button_x = self.width() - button_size - button_margin
        button_y = button_margin

        if (button_x <= pos.x() <= button_x + button_size and
            button_y <= pos.y() <= button_y + button_size):
            self._prepare_control_click(pos)  # исправлено: предотвращаем ложный свайп после клика полноэкранной кнопки
            self.toggle_fullscreen()
            return True

        return False

    def toggle_fullscreen(self):
        """Toggle fullscreen mode"""
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            self.showFullScreen()
            # Set focus to ensure keyboard events are captured
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            self.activateWindow()
        else:
            self.showNormal()
        self.save_settings()
        self.update()

    def toggle_autostart(self):
        """Toggle autostart on/off"""
        current_status = AutostartManager.get_autostart_status()

        if current_status:
            # Disable autostart
            success = AutostartManager.disable_autostart()
            if success:
                self.show_notification(
                    self._tr("autostart_disabled"),
                    duration=3000,
                    notification_type="info"
                )
            else:
                self.show_notification(
                    self._tr("autostart_error"),
                    duration=4000,
                    notification_type="error"
                )
        else:
            # Enable autostart
            success = AutostartManager.enable_autostart()
            if success:
                self.show_notification(
                    self._tr("autostart_enabled"),
                    duration=3000,
                    notification_type="success"
                )
            else:
                self.show_notification(
                    self._tr("autostart_error"),
                    duration=4000,
                    notification_type="error"
                )

        # Update UI to reflect new state
        self.update()

    def open_wifi_settings(self):
        """Open WiFi settings popup"""
        # Close any existing wifi popup
        if hasattr(self, '_wifi_popup') and self._wifi_popup:
            self._wifi_popup.close()
        
        self._wifi_popup = WiFiPopup(self)
        self._wifi_popup.closed.connect(self._on_wifi_popup_closed)
        self._wifi_popup.show()
    
    def _on_wifi_popup_closed(self):
        """Handle WiFi popup close"""
        self._wifi_popup = None

    def _show_text_input_popup(self, field_name: str, target_input: QLineEdit):
        """Show text input popup with keyboard for the given input field"""
        if hasattr(self, '_text_input_popup') and self._text_input_popup:
            self._text_input_popup.close()
        
        # Store field name instead of widget reference
        self._text_input_field = field_name
        self._text_input_popup = TextInputPopup(
            self, 
            title=f"Enter {field_name}",
            initial_text=target_input.text(),
            placeholder=f"Enter {field_name.lower()}..."
        )
        self._text_input_popup.text_entered.connect(self._on_text_input_entered)
        self._text_input_popup.cancelled.connect(self._on_text_input_cancelled)
        self._text_input_popup.show()
    
    def _on_text_input_entered(self, text: str):
        """Handle text entered from popup"""
        field = getattr(self, '_text_input_field', None)
        if field == "URL" and hasattr(self, 'webview_url_input'):
            try:
                self.webview_url_input.setText(text)
            except RuntimeError:
                pass
        elif field == "Title" and hasattr(self, 'webview_title_input'):
            try:
                self.webview_title_input.setText(text)
            except RuntimeError:
                pass
        self._text_input_popup = None
        self._text_input_field = None
    
    def _on_text_input_cancelled(self):
        """Handle text input popup cancelled"""
        self._text_input_popup = None
        self._text_input_field = None

    def update_webview_url(self, original_url: str, new_url: str):
        """Update webview URL in slide settings when user navigates"""
        if original_url == new_url:
            return
        
        # Find the slide with this original URL and update it
        for slide in self.slides:
            if slide.get('type') == SlideType.WEBVIEW:
                if slide.get('data', {}).get('url') == original_url:
                    slide['data']['url'] = new_url
                    self.save_settings()
                    break
    
    def show_webview_keyboard(self, element_id: str, current_value: str):
        """Show keyboard for webview input field"""
        # Don't reopen if already showing or recently closed
        if hasattr(self, '_webview_keyboard_popup') and self._webview_keyboard_popup:
            return
        if hasattr(self, '_webview_keyboard_cooldown') and self._webview_keyboard_cooldown:
            return
        
        self._webview_keyboard_popup = TextInputPopup(
            self,
            title="Enter Text",
            initial_text=current_value,
            placeholder="Type here..."
        )
        self._webview_keyboard_popup.text_entered.connect(self._on_webview_keyboard_entered)
        self._webview_keyboard_popup.cancelled.connect(self._on_webview_keyboard_cancelled)
        self._webview_keyboard_popup.show()
    
    def _on_webview_keyboard_entered(self, text: str):
        """Handle text entered for webview"""
        if hasattr(self, 'webview_manager') and self.webview_manager:
            self.webview_manager.set_input_value(text)
        self._webview_keyboard_popup = None
        # Cooldown to prevent immediate reopen
        self._webview_keyboard_cooldown = True
        QTimer.singleShot(500, self._clear_keyboard_cooldown)
    
    def _on_webview_keyboard_cancelled(self):
        """Handle webview keyboard cancelled"""
        self._webview_keyboard_popup = None
        # Cooldown to prevent immediate reopen
        self._webview_keyboard_cooldown = True
        QTimer.singleShot(500, self._clear_keyboard_cooldown)
    
    def _clear_keyboard_cooldown(self):
        """Clear keyboard cooldown"""
        self._webview_keyboard_cooldown = False

    def is_click_on_current_card(self, pos: QPoint) -> bool:
        """Detect clicks on the active slide in normal mode"""
        if self.edit_mode or not (0 <= self.current_slide < len(self.slides)):
            return False

        slide = self.slides[self.current_slide]
        if slide['type'] != SlideType.ADD:
            return False

        width = self.width()
        height = self.height()
        if width <= 0 or height <= 0:
            return False

        interact_rect = QRect(
            int(width * 0.25),
            int(height * 0.25),
            int(width * 0.5),
            int(height * 0.5)
        )
        return interact_rect.contains(pos)

    def check_card_click(self, pos: QPoint) -> bool:
        """Check if the centered card was clicked in edit mode"""
        if not self.edit_mode:
            return False
        
        # Card is drawn at scale 0.62 with offset_y
        # The actual visual card position needs to account for transformations
        scale = self.slide_container.scale
        offset_y = self.slide_container.offset_y
        
        # Original card dimensions in the transformed space
        card_width = int(self.width() * 0.62)
        card_height = int(self.height() * 0.62)
        start_y = 80
        
        center_x = self.width() // 2
        center_y = self.height() // 2
        
        # Calculate actual visual position after transformations
        # The card is scaled around center, then translated
        visual_card_x = center_x - (card_width * scale) // 2
        visual_card_y = center_y + offset_y - (card_height * scale) // 2 + (start_y * scale)
        visual_card_width = card_width * scale
        visual_card_height = card_height * scale
        
        # Check if click is within the visual bounds
        if (visual_card_x <= pos.x() <= visual_card_x + visual_card_width and 
            visual_card_y <= pos.y() <= visual_card_y + visual_card_height):
            
            slide = self.slides[self.current_slide]
            
            if slide['type'] == SlideType.ADD:
                self.show_add_menu()
            elif slide['type'] == SlideType.CLOCK:
                self.open_clock_editor()
            elif slide['type'] == SlideType.WEATHER:
                self.open_weather_editor()
            elif slide['type'] == SlideType.CUSTOM:
                self.open_custom_editor(self.current_slide)
            elif slide['type'] == SlideType.WEBVIEW:
                self.open_webview_editor(self.current_slide)

            return True
        
        return False

    def show_add_menu(self):
        """Show menu to add new cards"""
        self.card_edit_mode = True
        self.hide_all_webviews()
        self._clear_i18n_widgets()
        self.active_panel_type = ("add_menu", None)
        self.setup_add_menu_panel()

    def setup_add_menu_panel(self):
        """Create panel for adding new cards"""
        self.edit_panel = AnimatedPanel(self)
        self.edit_panel.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(20, 20, 20, 250);
                border: 2px solid #444;
                border-radius: 20px;
            }}
            QLabel {{ color: white; font-weight: bold; font-size: 16px; font-family: '{self.font_family}'; }}
            QPushButton {{
                background-color: #333;
                border: 2px solid #555;
                border-radius: {int(10 * self.scale_factor)}px;
                color: white;
                font-size: {self.get_scaled_font_size(18)}px;
                padding: {int(15 * self.scale_factor)}px {int(20 * self.scale_factor)}px;
                min-width: {int(200 * self.scale_factor)}px;
                min-height: {int(50 * self.scale_factor)}px;
                font-family: '{self.font_family}';
            }}
            QPushButton:hover {{
                background-color: #444;
                border: 2px solid #666;
            }}
        """)
        
        layout = QVBoxLayout(self.edit_panel)
        layout.setSpacing(int(15 * self.scale_factor))
        layout.setContentsMargins(
            int(30 * self.scale_factor),
            int(20 * self.scale_factor),
            int(30 * self.scale_factor),
            int(20 * self.scale_factor)
        )
        
        title = QLabel()
        self._register_i18n_widget(title, "add_menu_title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"font-size: {self.get_scaled_font_size(22)}px; font-weight: bold; font-family: '{self.font_family}';")
        layout.addWidget(title)
        
        # Weather button
        has_weather = any(s['type'] == SlideType.WEATHER for s in self.slides)
        weather_btn = QPushButton()
        self._register_i18n_widget(weather_btn, "weather_widget_button")
        weather_btn.setEnabled(not has_weather)
        if has_weather:
            weather_btn.setStyleSheet(f"""
                QPushButton:disabled {{
                    background-color: #222;
                    color: #666;
                    border: 2px solid #333;
                    font-family: '{self.font_family}';
                }}
            """)
        weather_btn.clicked.connect(self.add_weather_widget)
        layout.addWidget(weather_btn)
        
        # Custom card button
        custom_btn = QPushButton()
        self._register_i18n_widget(custom_btn, "custom_card_button")
        custom_btn.clicked.connect(self.add_custom_card)
        layout.addWidget(custom_btn)

        # Webview button
        webview_btn = QPushButton()
        self._register_i18n_widget(webview_btn, "webview_button")
        webview_btn.clicked.connect(self.add_webview)
        layout.addWidget(webview_btn)

        # Cancel button
        cancel_btn = QPushButton()
        self._register_i18n_widget(cancel_btn, "cancel_button")
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #555;
                border: 2px solid #666;
                font-family: '{self.font_family}';
            }}
            QPushButton:hover {{
                background-color: #666;
            }}
        """)
        cancel_btn.clicked.connect(self.exit_card_edit_mode)
        layout.addWidget(cancel_btn)
        
        panel_width = int(380 * self.scale_factor)
        panel_height = int(480 * self.scale_factor)
        self.edit_panel.setGeometry(
            (self.width() - panel_width) // 2,
            (self.height() - panel_height) // 2,
            panel_width, panel_height
        )

        # Setup and start panel animation
        self.edit_panel.set_opacity(0.0)
        self.edit_panel.set_scale(0.8)
        self.edit_panel.show()
        self._animate_panel_in()

    def _default_weather_data(self) -> Dict[str, bool]:
        """Return default visibility settings for weather slide elements."""
        return {
            'show_temp': True,
            'show_icon': True,
            'show_desc': True,
            'show_wind': True,
        }

    def _ensure_weather_defaults(self, data: Optional[dict]) -> dict:
        """Ensure weather slide data has all expected keys set."""
        if data is None:
            data = {}
        for key, value in self._default_weather_data().items():
            data.setdefault(key, value)
        return data

    def save_weather_settings(self, checked=False):
        """Persist weather slide configuration"""
        if self.current_edit_index is None or not (0 <= self.current_edit_index < len(self.slides)):
            self.exit_card_edit_mode()
            return

        slide = self.slides[self.current_edit_index]
        if slide['type'] != SlideType.WEATHER:
            self.exit_card_edit_mode()
            return

        slide_data = self._ensure_weather_defaults(slide.setdefault('data', {}))
        slide_data['show_temp'] = self.show_temp_cb.isChecked()
        slide_data['show_icon'] = self.show_icon_cb.isChecked()
        slide_data['show_desc'] = self.show_desc_cb.isChecked()
        slide_data['show_wind'] = self.show_wind_cb.isChecked()
        
        self._is_new_card = False  # Confirmed creation/edit
        self.save_settings()
        self.update()
        self.exit_card_edit_mode()

    def add_weather_widget(self, checked=False):
        """Add weather widget card"""
        has_weather = any(s['type'] == SlideType.WEATHER for s in self.slides)
        if not has_weather:
            # Insert before the ADD card
            add_index = len(self.slides) - 1
            self.slides.insert(add_index, {'type': SlideType.WEATHER, 'data': self._default_weather_data()})
            self.current_slide = add_index
            self.save_settings()
            self._is_new_card = True  # Flag as new card
        self.exit_card_edit_mode()

    def add_custom_card(self, checked=False):
        """Add custom card"""
        # Insert before the ADD card
        add_index = len(self.slides) - 1
        self.slides.insert(add_index, {
            'type': SlideType.CUSTOM,
            'data': {'text': self._tr('custom_default_text')}
        })
        self.current_slide = add_index
        self.save_settings()
        self._is_new_card = True  # Flag as new card
        
        # Open editor immediately
        self.card_edit_mode = True
        self.hide_all_webviews()
        self.current_edit_index = add_index
        self._clear_i18n_widgets()
        self.setup_custom_edit_panel()

    def add_webview(self, checked=False):
        """Add new webview card"""
        # Insert before the ADD card
        add_index = len(self.slides) - 1
        self.slides.insert(add_index, {
            'type': SlideType.WEBVIEW,
            'data': {
                'url': 'https://google.com',
                'title': self._tr('webview_default_title')
            }
        })
        self.current_slide = add_index
        self.save_settings()
        self._is_new_card = True  # Flag as new card
        
        # Open editor immediately
        self.card_edit_mode = True
        self.hide_all_webviews()
        self.current_edit_index = add_index
        self._clear_i18n_widgets()
        self.setup_webview_edit_panel()

    def open_clock_editor(self):
        """Open clock editor panel"""
        self.card_edit_mode = True
        self.hide_all_webviews()
        self._clear_i18n_widgets()
        self.setup_clock_edit_panel()

    def open_weather_editor(self):
        """Open weather editor panel"""
        self.card_edit_mode = True
        self.hide_all_webviews()
        self.current_edit_index = self.current_slide
        self._clear_i18n_widgets()
        self.setup_weather_edit_panel()

    def open_custom_editor(self, index: int):
        """Open custom slide editor"""
        self.card_edit_mode = True
        self.hide_all_webviews()
        self.current_edit_index = index
        self._clear_i18n_widgets()
        self.setup_custom_edit_panel()

    def open_webview_editor(self, index: int):
        """Open universal webview slide editor"""
        self.card_edit_mode = True
        self.hide_all_webviews()
        self.current_edit_index = index
        self._clear_i18n_widgets()
        self.setup_webview_edit_panel()

    def setup_clock_edit_panel(self):
        """Create clock editor panel"""
        self.active_panel_type = ("clock", None)
        _, layout = self._create_settings_panel("clock_editor_title", width_ratio=0.50, height_ratio=0.68)

        self.brightness_slider = None
        self.auto_brightness_checkbox = None

        # Brightness label and slider row
        brightness_label_row = QHBoxLayout()
        brightness_label = self._settings_section_label("brightness_label")
        brightness_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        brightness_label_row.addWidget(brightness_label)
        brightness_label_row.addStretch()
        layout.addLayout(brightness_label_row)

        layout.addSpacing(self.get_spacing(6, 3))

        auto_row = QHBoxLayout()
        self.auto_brightness_checkbox = QCheckBox()
        self._register_i18n_widget(self.auto_brightness_checkbox, "auto_brightness_toggle")
        cb_font_size = self.get_ui_size(12, 10)
        cb_padding = self.get_spacing(2, 1)
        self.auto_brightness_checkbox.setStyleSheet(
            f"QCheckBox {{ font-size: {cb_font_size}px; padding: {cb_padding}px 0; font-family: '{self.font_family}'; }}"
        )
        self.auto_brightness_checkbox.stateChanged.connect(self._handle_auto_brightness_checkbox)
        auto_row.addWidget(self.auto_brightness_checkbox)
        auto_row.addStretch()
        layout.addLayout(auto_row)

        layout.addSpacing(self.get_spacing(4, 3))

        brightness_slider_row = QHBoxLayout()
        self.brightness_slider = ModernSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(10, 100)
        slider_width = self.get_ui_size(260, 180)
        self.brightness_slider.setFixedWidth(slider_width)
        self.brightness_slider.setValue(int(self._manual_brightness * 100))
        self.brightness_slider.valueChanged.connect(self._on_brightness_slider_changed)
        brightness_slider_row.addWidget(self.brightness_slider)
        brightness_slider_row.addStretch()
        layout.addLayout(brightness_slider_row)
        self._set_auto_brightness_controls_state()

        layout.addSpacing(self.get_spacing(12, 8))

        # Digits color row
        digits_row = QHBoxLayout()
        digits_label = self._settings_section_label("digits_label")
        digits_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        digits_row.addWidget(digits_label)
        digits_row.addSpacing(self.get_spacing(8, 5))
        btn_size = self.get_ui_size(24, 20)
        digit_color_btn = ModernColorButton(self.digit_color, size=btn_size)
        digit_color_btn.setText("")
        digit_color_btn.color_changed.connect(lambda c: setattr(self, 'digit_color', c))
        digits_row.addWidget(digit_color_btn)
        digits_row.addStretch()
        layout.addLayout(digits_row)

        layout.addSpacing(self.get_spacing(10, 6))

        # Colon color row
        colon_row = QHBoxLayout()
        colon_label = self._settings_section_label("colon_label")
        colon_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        colon_row.addWidget(colon_label)
        colon_row.addSpacing(self.get_spacing(8, 5))
        colon_color_btn = ModernColorButton(self.colon_color, size=btn_size)
        colon_color_btn.setText("")
        colon_color_btn.color_changed.connect(lambda c: setattr(self, 'colon_color', c))
        colon_row.addWidget(colon_color_btn)
        colon_row.addStretch()
        layout.addLayout(colon_row)

        layout.addSpacing(self.get_spacing(10, 6))

        # Background color row
        bg_row = QHBoxLayout()
        bg_label = self._settings_section_label("background_label")
        bg_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        bg_row.addWidget(bg_label)
        bg_row.addSpacing(self.get_spacing(8, 5))
        bg_color_btn = ModernColorButton(self.background_color, "background", size=btn_size)
        bg_color_btn.setText("")
        bg_color_btn.color_changed.connect(lambda c: setattr(self, 'background_color', c))
        bg_row.addWidget(bg_color_btn)
        bg_row.addStretch()
        layout.addLayout(bg_row)

        layout.addStretch()

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(self.get_spacing(8, 6))
        buttons_row.addStretch()

        cancel_btn = QPushButton()
        cancel_btn.setProperty("buttonRole", "secondary")
        self._register_i18n_widget(cancel_btn, "cancel_button")
        cancel_btn.clicked.connect(self.exit_card_edit_mode)
        buttons_row.addWidget(cancel_btn)

        save_btn = QPushButton()
        save_btn.setProperty("buttonRole", "primary")
        self._register_i18n_widget(save_btn, "save_button")
        save_btn.clicked.connect(self.save_clock_settings)
        buttons_row.addWidget(save_btn)

        buttons_row.addStretch()
        layout.addLayout(buttons_row)

    def save_clock_settings(self, checked=False):
        """Commit clock settings and close the panel"""
        self.save_settings()
        self.exit_card_edit_mode()

    def setup_weather_edit_panel(self):
        """Create weather editor panel"""
        self.active_panel_type = ("weather", None)
        _, layout = self._create_settings_panel("weather_editor_title", width_ratio=0.45, height_ratio=0.62)

        slide = self.slides[self.current_slide]
        slide_data = self._ensure_weather_defaults(slide.get('data', {}))

        layout.addSpacing(self.get_spacing(8, 4))

        cb_font_size = self.get_ui_size(12, 10)
        cb_padding = self.get_spacing(4, 2)

        self.show_temp_cb = QCheckBox()
        self._register_i18n_widget(self.show_temp_cb, "show_temp")
        self.show_temp_cb.setChecked(slide_data.get('show_temp', True))
        self.show_temp_cb.setStyleSheet(f"QCheckBox {{ font-size: {cb_font_size}px; padding: {cb_padding}px 0; font-family: '{self.font_family}'; }}")
        cb_row1 = QHBoxLayout()
        cb_row1.addWidget(self.show_temp_cb)
        cb_row1.addStretch()
        layout.addLayout(cb_row1)

        layout.addSpacing(self.get_spacing(4, 2))

        self.show_icon_cb = QCheckBox()
        self._register_i18n_widget(self.show_icon_cb, "show_icon")
        self.show_icon_cb.setChecked(slide_data.get('show_icon', True))
        self.show_icon_cb.setStyleSheet(f"QCheckBox {{ font-size: {cb_font_size}px; padding: {cb_padding}px 0; font-family: '{self.font_family}'; }}")
        cb_row2 = QHBoxLayout()
        cb_row2.addWidget(self.show_icon_cb)
        cb_row2.addStretch()
        layout.addLayout(cb_row2)

        layout.addSpacing(self.get_spacing(4, 2))

        self.show_desc_cb = QCheckBox()
        self._register_i18n_widget(self.show_desc_cb, "show_desc")
        self.show_desc_cb.setChecked(slide_data.get('show_desc', True))
        self.show_desc_cb.setStyleSheet(f"QCheckBox {{ font-size: {cb_font_size}px; padding: {cb_padding}px 0; font-family: '{self.font_family}'; }}")
        cb_row3 = QHBoxLayout()
        cb_row3.addWidget(self.show_desc_cb)
        cb_row3.addStretch()
        layout.addLayout(cb_row3)

        layout.addSpacing(self.get_spacing(4, 2))

        self.show_wind_cb = QCheckBox()
        self._register_i18n_widget(self.show_wind_cb, "show_wind")
        self.show_wind_cb.setChecked(slide_data.get('show_wind', True))
        self.show_wind_cb.setStyleSheet(f"QCheckBox {{ font-size: {cb_font_size}px; padding: {cb_padding}px 0; font-family: '{self.font_family}'; }}")
        cb_row4 = QHBoxLayout()
        cb_row4.addWidget(self.show_wind_cb)
        cb_row4.addStretch()
        layout.addLayout(cb_row4)

        layout.addStretch()

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(self.get_spacing(8, 6))
        buttons_row.addStretch()

        # Delete button (only for non-essential slides)
        delete_btn = QPushButton()
        delete_btn.setProperty("buttonRole", "delete")
        btn_font_size = self.get_ui_size(12, 10)
        btn_padding_v = self.get_ui_size(8, 6)
        btn_padding_h = self.get_ui_size(16, 12)
        btn_radius = self.get_ui_size(8, 6)
        btn_min_w = self.get_ui_size(75, 60)
        btn_min_h = self.get_ui_size(32, 26)
        delete_btn.setStyleSheet(f"""
            QPushButton[buttonRole="delete"] {{
                background-color: #dc3545;
                color: white;
                border: none;
                border-radius: {btn_radius}px;
                padding: {btn_padding_v}px {btn_padding_h}px;
                font-weight: 600;
                font-size: {btn_font_size}px;
                min-width: {btn_min_w}px;
                min-height: {btn_min_h}px;
                font-family: '{self.font_family}';
            }}
        """)
        self._register_i18n_widget(delete_btn, "delete_button")
        delete_btn.clicked.connect(self.confirm_delete_card)
        buttons_row.addWidget(delete_btn)

        cancel_btn = QPushButton()
        cancel_btn.setProperty("buttonRole", "secondary")
        self._register_i18n_widget(cancel_btn, "cancel_button")
        cancel_btn.clicked.connect(self.exit_card_edit_mode)
        buttons_row.addWidget(cancel_btn)

        save_btn = QPushButton()
        save_btn.setProperty("buttonRole", "primary")
        self._register_i18n_widget(save_btn, "save_button")
        save_btn.clicked.connect(self.save_weather_settings)
        buttons_row.addWidget(save_btn)

        buttons_row.addStretch()
        layout.addLayout(buttons_row)

    def setup_custom_edit_panel(self):
        """Create custom slide editor panel"""
        self.active_panel_type = ("custom", self.current_edit_index)
        _, layout = self._create_settings_panel("custom_editor_title", width_ratio=0.55, height_ratio=0.72)

        layout.addSpacing(self.get_spacing(8, 4))

        self.custom_text_edit = QTextEdit()
        self.custom_text_edit.setPlainText(
            self.slides[self.current_edit_index]['data'].get('text', '')
        )
        text_edit_height = self.get_ui_size(220, 150)
        text_font_size = self.get_ui_size(13, 11)
        text_padding = self.get_ui_size(10, 6)
        text_radius = self.get_ui_size(7, 5)
        self.custom_text_edit.setMinimumHeight(text_edit_height)
        self.custom_text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: rgba(255, 255, 255, 8);
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: {text_radius}px;
                padding: {text_padding}px;
                color: #f0f0f0;
                font-size: {text_font_size}px;
                line-height: 1.4;
                font-family: '{self.font_family}';
            }}
        """)
        layout.addWidget(self.custom_text_edit)

        layout.addStretch()

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(max(6, int(8 * self.scale_factor)))
        buttons_row.addStretch()

        # Delete button for custom slides
        delete_btn = QPushButton()
        delete_btn.setProperty("buttonRole", "delete")
        btn_font_size = self.get_ui_size(12, 10)
        btn_padding_v = self.get_ui_size(8, 6)
        btn_padding_h = self.get_ui_size(16, 12)
        btn_radius = self.get_ui_size(8, 6)
        btn_min_w = self.get_ui_size(75, 60)
        btn_min_h = self.get_ui_size(32, 26)
        delete_btn.setStyleSheet(f"""
            QPushButton[buttonRole="delete"] {{
                background-color: #dc3545;
                color: white;
                border: none;
                border-radius: {btn_radius}px;
                padding: {btn_padding_v}px {btn_padding_h}px;
                font-weight: 600;
                font-size: {btn_font_size}px;
                min-width: {btn_min_w}px;
                min-height: {btn_min_h}px;
                font-family: '{self.font_family}';
            }}
        """)
        self._register_i18n_widget(delete_btn, "delete_button")
        delete_btn.clicked.connect(self.confirm_delete_card)
        buttons_row.addWidget(delete_btn)

        cancel_btn = QPushButton()
        cancel_btn.setProperty("buttonRole", "secondary")
        self._register_i18n_widget(cancel_btn, "cancel_button")
        cancel_btn.clicked.connect(self.exit_card_edit_mode)
        buttons_row.addWidget(cancel_btn)

        save_btn = QPushButton()
        save_btn.setProperty("buttonRole", "primary")
        self._register_i18n_widget(save_btn, "save_button")
        save_btn.clicked.connect(self.save_custom_slide)
        buttons_row.addWidget(save_btn)

        buttons_row.addStretch()
        layout.addLayout(buttons_row)

    def save_custom_slide(self, checked=False):
        """Save custom slide content"""
        if hasattr(self, 'custom_text_edit'):
            text = self.custom_text_edit.toPlainText()
            self.slides[self.current_edit_index]['data']['text'] = text
            self._is_new_card = False  # Confirmed creation/edit
            self.save_settings()
        self.exit_card_edit_mode()

    def setup_webview_edit_panel(self):
        """Create universal webview editor panel"""
        self.active_panel_type = ("webview", self.current_edit_index)
        _, layout = self._create_settings_panel("webview_editor_title", width_ratio=0.55, height_ratio=0.65)

        layout.addSpacing(self.get_spacing(8, 4))

        # URL input
        url_label = QLabel()
        self._register_i18n_widget(url_label, "youtube_url_label")
        url_label_font_size = self.get_ui_size(12, 10)
        url_label.setStyleSheet(f"color: #ccc; font-size: {url_label_font_size}px; font-family: '{self.font_family}';")
        layout.addWidget(url_label)

        input_height = self.get_ui_size(32, 26)
        input_font_size = self.get_ui_size(12, 10)
        input_padding = self.get_ui_size(8, 6)
        input_radius = self.get_ui_size(6, 4)
        
        url_row = QHBoxLayout()
        url_row.setSpacing(6)
        
        self.webview_url_input = QLineEdit()
        self.webview_url_input.setText(
            self.slides[self.current_edit_index]['data'].get('url', '')
        )
        self.webview_url_input.setMinimumHeight(input_height)
        self.webview_url_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: rgba(255, 255, 255, 8);
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: {input_radius}px;
                padding: {input_padding}px;
                color: #f0f0f0;
                font-size: {input_font_size}px;
                font-family: '{self.font_family}';
            }}
        """)
        url_row.addWidget(self.webview_url_input)
        
        url_kbd_btn = QPushButton("⌨")
        url_kbd_btn.setFixedSize(input_height, input_height)
        url_kbd_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 15);
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: {input_radius}px;
                color: #aaa;
                font-size: 14px;
            }}
            QPushButton:pressed {{ background-color: rgba(255, 255, 255, 30); }}
        """)
        url_kbd_btn.clicked.connect(lambda: self._show_text_input_popup("URL", self.webview_url_input))
        url_row.addWidget(url_kbd_btn)
        
        layout.addLayout(url_row)

        layout.addSpacing(self.get_spacing(12, 8))

        # Title input
        title_label = QLabel()
        self._register_i18n_widget(title_label, "youtube_title_label")
        title_label.setStyleSheet(f"color: #ccc; font-size: {url_label_font_size}px; font-family: '{self.font_family}';")
        layout.addWidget(title_label)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        
        self.webview_title_input = QLineEdit()
        self.webview_title_input.setText(
            self.slides[self.current_edit_index]['data'].get('title', self._tr('youtube_default_title'))
        )
        self.webview_title_input.setMinimumHeight(input_height)
        self.webview_title_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: rgba(255, 255, 255, 8);
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: {input_radius}px;
                padding: {input_padding}px;
                color: #f0f0f0;
                font-size: {input_font_size}px;
                font-family: '{self.font_family}';
            }}
        """)
        title_row.addWidget(self.webview_title_input)
        
        title_kbd_btn = QPushButton("⌨")
        title_kbd_btn.setFixedSize(input_height, input_height)
        title_kbd_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 15);
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: {input_radius}px;
                color: #aaa;
                font-size: 14px;
            }}
            QPushButton:pressed {{ background-color: rgba(255, 255, 255, 30); }}
        """)
        title_kbd_btn.clicked.connect(lambda: self._show_text_input_popup("Title", self.webview_title_input))
        title_row.addWidget(title_kbd_btn)
        
        layout.addLayout(title_row)

        layout.addStretch()

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(max(6, int(8 * self.scale_factor)))
        buttons_row.addStretch()

        # Delete button
        delete_btn = QPushButton()
        delete_btn.setProperty("buttonRole", "delete")
        btn_font_size = self.get_ui_size(12, 10)
        btn_padding_v = self.get_ui_size(8, 6)
        btn_padding_h = self.get_ui_size(16, 12)
        btn_radius = self.get_ui_size(8, 6)
        btn_min_w = self.get_ui_size(75, 60)
        btn_min_h = self.get_ui_size(32, 26)
        delete_btn.setStyleSheet(f"""
            QPushButton[buttonRole="delete"] {{
                background-color: #dc3545;
                color: white;
                border: none;
                border-radius: {btn_radius}px;
                padding: {btn_padding_v}px {btn_padding_h}px;
                font-weight: 600;
                font-size: {btn_font_size}px;
                min-width: {btn_min_w}px;
                min-height: {btn_min_h}px;
                font-family: '{self.font_family}';
            }}
        """)
        self._register_i18n_widget(delete_btn, "delete_button")
        delete_btn.clicked.connect(self.confirm_delete_card)
        buttons_row.addWidget(delete_btn)

        cancel_btn = QPushButton()
        cancel_btn.setProperty("buttonRole", "secondary")
        self._register_i18n_widget(cancel_btn, "cancel_button")
        cancel_btn.clicked.connect(self.exit_card_edit_mode)
        buttons_row.addWidget(cancel_btn)

        save_btn = QPushButton()
        save_btn.setProperty("buttonRole", "primary")
        self._register_i18n_widget(save_btn, "save_button")
        save_btn.clicked.connect(self.save_webview)
        buttons_row.addWidget(save_btn)

        buttons_row.addStretch()
        layout.addLayout(buttons_row)


    def save_webview(self, checked=False):
        """Save webview slide content"""
        if hasattr(self, 'webview_url_input') and hasattr(self, 'webview_title_input'):
            url = self.webview_url_input.text()
            title = self.webview_title_input.text()
            self.slides[self.current_edit_index]['data']['url'] = url
            self.slides[self.current_edit_index]['data']['title'] = title
            self._is_new_card = False  # Confirmed creation/edit
            self.save_settings()
            # Reset webview state
            self.webview_manager.page_loaded = False
            self.webview_manager.current_url = ""
        self.exit_card_edit_mode()

    def confirm_delete_card(self, checked=False):
        """Show confirmation dialog for deleting a card"""
        if self.current_edit_index is None or self.current_edit_index >= len(self.slides):
            return

        slide = self.slides[self.current_edit_index]
        if slide['type'] == SlideType.CLOCK:
            return  # Cannot delete clock slide

        # Use internal confirmation popup
        self.show_confirmation(
            self._tr("delete_confirm_title"),
            self._tr("delete_confirm_message"),
            self.delete_current_card,
            confirm_text=self._tr("yes_button"),
            cancel_text=self._tr("no_button")
        )

    def delete_current_card(self):
        """Delete the currently edited card"""
        if self.current_edit_index is None or self.current_edit_index >= len(self.slides):
            return

        slide = self.slides[self.current_edit_index]
        if slide['type'] == SlideType.CLOCK:
            return  # Cannot delete clock slide

        # Remove the slide
        del self.slides[self.current_edit_index]

        # Adjust current slide index if necessary
        if self.current_slide >= len(self.slides):
            self.current_slide = len(self.slides) - 1
        elif self.current_slide > self.current_edit_index:
            self.current_slide -= 1

        self.save_settings()
        self.exit_card_edit_mode()
        self.update()
        self.update_active_webviews()

    def exit_card_edit_mode(self, _checked=None):
        """Exit card edit mode. _checked parameter absorbs Qt button signal."""
        
        # Handle cancellation of new card creation
        if self._is_new_card and self.current_edit_index is not None:
            if 0 <= self.current_edit_index < len(self.slides):
                del self.slides[self.current_edit_index]
                if self.current_slide >= len(self.slides):
                    self.current_slide = max(0, len(self.slides) - 1)
                self.save_settings()
        self._is_new_card = False

        def cleanup_panel():
            self._cleanup_panel_animations()
            if self.edit_panel:
                self.edit_panel.deleteLater()
                self.edit_panel = None
            self.card_edit_mode = False
            self.active_panel_type = None
            self.current_edit_index = None
            self._clear_i18n_widgets()
            self.brightness_slider = None
            self.auto_brightness_checkbox = None
            self.save_settings()
            self.update()
            self._edit_panel_ratios = None
            self.update_active_webviews()

        if self.edit_panel:
            self._animate_panel_out(cleanup_panel)
        else:
            cleanup_panel()

    def enter_edit_mode(self):
        """Enter edit mode"""
        if self.edit_mode or self._edit_transition_active:
            return

        self._edit_mode_entry_slide = max(0, min(self.current_slide, len(self.slides) - 1)) if self.slides else 0
        self.edit_mode = True
        self.hide_all_webviews()  # Hide embedded webviews when entering edit mode
        self._begin_edit_transition(self.scale_animation,
                                    self.offset_y_animation,
                                    self.offset_animation)

        # Animate into edit view
        self._start_property_animation(self.scale_animation, 0.62)
        self._start_property_animation(self.offset_y_animation, -self.height() * 0.15)
        self._start_property_animation(self.offset_animation, -self.current_slide * self.width())

        self.show_navigation()
        self.nav_hide_timer.stop()
        self.update()

    def exit_edit_mode(self):
        """Exit edit mode"""
        if not self.edit_mode or self._edit_transition_active:
            return

        self._stop_reorder_auto_scroll()
        self.edit_mode = False
        if self.slides:
            target_slide = max(0, min(self._edit_mode_entry_slide, len(self.slides) - 1))
            if target_slide != self.current_slide:
                self.current_slide = target_slide
        self._begin_edit_transition(self.scale_animation,
                                    self.offset_y_animation,
                                    self.offset_animation)

        # Animate back to normal view
        self._start_property_animation(self.scale_animation, 1.0)
        self._start_property_animation(self.offset_y_animation, 0.0)
        self._start_property_animation(self.offset_animation, -self.current_slide * self.width())

        self.reset_navigation_timer()
        self.save_settings()
        self.update()
        self._edit_mode_entry_slide = self.current_slide
        # Don't call update_active_webviews() here - it will be called after animations finish

    def next_slide(self, velocity: float = 0):
        """Move to next slide"""
        if len(self.slides) > 0 and self.current_slide < len(self.slides) - 1:
            if self.edit_mode:
                self._finalize_offset_animation()
            self.current_slide += 1
            self._animate_slide_with_velocity(velocity)
            self.reset_navigation_timer()
            self.reset_clock_return_timer()
            self.update()
            self.update_active_webviews()

    def previous_slide(self, velocity: float = 0):
        """Move to previous slide"""
        if len(self.slides) > 0 and self.current_slide > 0:
            if self.edit_mode:
                self._finalize_offset_animation()
            self.current_slide -= 1
            self._animate_slide_with_velocity(velocity)
            self.reset_navigation_timer()
            self.reset_clock_return_timer()
            self.update()
            self.update_active_webviews()
    
    def _animate_slide_with_velocity(self, velocity: float = 0):
        """Animate to current slide with duration based on swipe velocity"""
        if len(self.slides) == 0:
            return
        
        self.current_slide = max(0, min(self.current_slide, len(self.slides) - 1))
        target_offset = -self.current_slide * self.width()
        
        if hasattr(self, 'offset_animation') and self.offset_animation:
            # Faster swipe = shorter animation (more responsive feel)
            if velocity > 800:
                duration = 200
            elif velocity > 500:
                duration = 280
            elif velocity > 300:
                duration = 320
            else:
                duration = 350
            
            self.offset_animation.setEasingCurve(QEasingCurve.Type.OutExpo)
            self.offset_animation.setDuration(duration)
            self._start_property_animation(self.offset_animation, float(target_offset))
        
        self.update_active_webviews()
        self.update()

    def get_embedded_card_geometry(self, slide_index: int = None) -> QRect:
        """Calculate geometry for embedded webview cards based on slide position

        Args:
            slide_index: The index of the slide this webview belongs to.
                        If None, uses current_slide.
        """
        # Get current offset from slide container
        offset_x = self.slide_container.get_offset_x() if self.slide_container else 0
        scale = self.slide_container.get_scale() if self.slide_container else 1.0
        offset_y = self.slide_container.get_offset_y() if self.slide_container else 0

        # Use provided slide_index or fall back to current_slide
        if slide_index is None:
            slide_index = self.current_slide

        # Add margin for card appearance (like on reference)
        margin_x = int(20 * self.scale_factor)
        margin_top = int(20 * self.scale_factor)
        # Leave space at bottom for navigation dots (42px + some padding)
        margin_bottom = int(70 * self.scale_factor)

        # Calculate the slide's base position in the slide strip
        slide_base_x = slide_index * self.width()

        # Calculate card position accounting for slide position and animation offset
        # offset_x is the horizontal animation offset (negative when sliding left)
        # This mirrors how painted slides are positioned in draw_slides_normal_mode
        card_x = margin_x + slide_base_x + offset_x
        card_y = offset_y + margin_top
        card_width = self.width() - 2 * margin_x
        card_height = self.height() - margin_top - margin_bottom

        # Apply scale if in edit mode
        if scale != 1.0:
            center_x = self.width() / 2
            center_y = self.height() / 2
            scaled_width = card_width * scale
            scaled_height = card_height * scale
            
            # Fix: Apply displacement to position cards correctly relative to current focus
            # This prevents all cards from stacking at the center during transitions
            displacement = slide_base_x + offset_x
            card_x = (center_x - scaled_width / 2) + displacement
            
            card_y = center_y - scaled_height / 2 + offset_y
            card_width = scaled_width
            card_height = scaled_height

        return QRect(int(card_x), int(card_y), int(card_width), int(card_height))

    def eventFilter(self, obj, event):
        """Filter events from webview to detect swipes"""
        # Check if event is from the universal webview
        if (self.webview_manager.webview and 
            obj == self.webview_manager.webview and 
            self.webview_manager.webview.isVisible()):
            
            webview = self.webview_manager.webview
            
            # Let touch events pass through for native scrolling (two-finger scroll)
            if event.type() in (QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate, QEvent.Type.TouchEnd):
                return False  # Don't intercept - let webview handle natively
            
            if event.type() == QEvent.Type.MouseButtonPress:
                self._webview_mouse_start = event.pos()
                self._active_webview_for_swipe = webview
                self._active_webview_type = SlideType.WEBVIEW
                self._webview_was_transparent = False
                return False

            if event.type() == QEvent.Type.MouseMove and self._webview_mouse_start is not None:
                delta_x = event.pos().x() - self._webview_mouse_start.x()
                delta_y = event.pos().y() - self._webview_mouse_start.y()

                if abs(delta_x) > 15 and abs(delta_x) > abs(delta_y) * 1.8:
                    if not self._webview_was_transparent:
                        webview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                        self._webview_was_transparent = True

                        parent_pos = webview.mapToParent(self._webview_mouse_start)
                        new_press = QMouseEvent(
                            QMouseEvent.Type.MouseButtonPress,
                            parent_pos,
                            event.button(),
                            Qt.MouseButton.LeftButton,
                            event.modifiers()
                        )
                        QApplication.sendEvent(self, new_press)
                    return False

                return False

            if event.type() == QEvent.Type.MouseButtonRelease:
                self._webview_mouse_start = None
                self._active_webview_for_swipe = None
                self._active_webview_type = None
                if self._webview_was_transparent:
                    QTimer.singleShot(100, lambda w=webview: self._restore_webview_interactivity(w))
                    self._webview_was_transparent = False
                return False

            return False

        return super().eventFilter(obj, event)

    def _get_webview_type(self, webview: Optional[QWebEngineView]) -> Optional[SlideType]:
        """Return slide type for a given webview instance"""
        if webview is None:
            return None
        if webview == self.webview_manager.webview:
            return SlideType.WEBVIEW
        return None

    def _restore_webview_interactivity(self, webview: Optional[QWebEngineView] = None):
        """Restore webview interactivity after swipe"""
        webview = webview or self._active_webview_for_swipe
        if webview is None:
            return

        slide_type = self._get_webview_type(webview)
        if slide_type is None:
            return

        # Only restore if we're still on a webview slide
        if 0 <= self.current_slide < len(self.slides):
            slide = self.slides[self.current_slide]
            if slide['type'] == slide_type:
                webview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)


    def show_webview(self, url: str):
        """Show webview with URL"""
        # Don't show in edit modes
        if self.edit_mode or self.card_edit_mode:
            return False
            
        # Load URL (will skip if already loaded)
        self.webview_manager.load_url(url)
            
        # Get current webview slide geometry
        webview_slide_index = self.get_slide_index_for_type(SlideType.WEBVIEW)
        if webview_slide_index >= 0 and webview_slide_index == self.current_slide:
            geom = self.get_embedded_card_geometry(webview_slide_index)
            # Show webview (will handle loading state internally)
            return self.webview_manager.show_webview(geom)
        return False

    def hide_webview(self):
        """Hide webview"""
        self.webview_manager.hide_webview()

    def hide_all_webviews(self):
        """Hide all embedded webviews"""
        self.hide_webview()
        self._active_webview_for_swipe = None
        self._active_webview_type = None
        self._webview_mouse_start = None
        self._webview_was_transparent = False

    def get_slide_index_for_type(self, slide_type: SlideType) -> int:
        """Find the slide index for a given slide type, returns -1 if not found"""
        for i, slide in enumerate(self.slides):
            if slide['type'] == slide_type:
                return i
        return -1

    def update_active_webviews(self):
        """Synchronize embedded webviews with slides (optimized for smooth transitions)

        Shows webview if it is visible in the viewport, even during transitions.
        """
        if self.edit_mode or self.card_edit_mode:
            self.hide_all_webviews()
            return

        # Find the most visible webview slide
        best_slide_index = -1
        best_intersection_area = 0
        best_geom = QRect()
        best_url = ""

        for i, slide in enumerate(self.slides):
            if slide['type'] == SlideType.WEBVIEW:
                geom = self.get_embedded_card_geometry(i)
                intersection = geom.intersected(self.rect())
                area = intersection.width() * intersection.height()
                
                if area > best_intersection_area:
                    best_intersection_area = area
                    best_slide_index = i
                    best_geom = geom
                    best_url = slide['data'].get('url', '')

        if best_slide_index != -1:
            if not best_url:
                self.hide_webview()
                return

            # Lazy init
            if not self._webview_initialized and not self._webview_init_pending:
                self._webview_init_pending = True
                self._webview_initialized = True
                QTimer.singleShot(50, lambda: self._init_and_show_webview(best_url))
                return

            self.webview_manager.load_url(best_url)
            self.webview_manager.show_webview(best_geom)
            
            # Ensure brightness overlay is on top
            if hasattr(self, 'brightness_overlay') and self.brightness_overlay.isVisible():
                self.brightness_overlay.raise_()
        else:
            self.hide_webview()
    
    def _init_and_show_webview(self, url: str):
        """Инициализация и показ webview при первом обращении"""
        if not self.webview_manager:
            self._webview_init_pending = False
            return
        # Создаём webview
        self.webview_manager.create_webview()
        # Загружаем URL
        self.webview_manager.load_url(url)
        self._webview_init_pending = False
        # Обновляем отображение
        self.update()

    def on_webview_load_finished_callback(self, success: bool):
        """Callback from WebviewManager when load finishes"""
        # Don't show webview in edit modes
        if self.edit_mode or self.card_edit_mode:
            return
            
        if success:
            # Only update if we're on a webview slide to prevent unnecessary repaints
            if 0 <= self.current_slide < len(self.slides):
                slide = self.slides[self.current_slide]
                if slide['type'] == SlideType.WEBVIEW:
                    # Page just loaded - show webview at correct position
                    webview_slide_index = self.get_slide_index_for_type(SlideType.WEBVIEW)
                    if webview_slide_index >= 0 and webview_slide_index == self.current_slide:
                        geom = self.get_embedded_card_geometry(webview_slide_index)
                        self.webview_manager.show_webview(geom)
                        
                        # Ensure brightness overlay is on top
                        if hasattr(self, 'brightness_overlay') and self.brightness_overlay.isVisible():
                            self.brightness_overlay.raise_()
                            
                        # Trigger minimal repaint only in webview area
                        self.update(geom)
                    return  # No full update needed
        # Only call full update on error
        if not success:
            self.update()

    def animate_to_current_slide(self):
        """Animate to current slide position"""
        # Ensure current_slide is within bounds
        if len(self.slides) == 0:
            return

        self.current_slide = max(0, min(self.current_slide, len(self.slides) - 1))
        target_offset = -self.current_slide * self.width()

        # Use different easing for slide transitions in normal mode
        if not self.edit_mode:
            if hasattr(self, 'offset_animation') and self.offset_animation:
                # Smoother animation with OutExpo for snappy feel
                self.offset_animation.setEasingCurve(QEasingCurve.Type.OutExpo)
                self.offset_animation.setDuration(350)
        else:
            if hasattr(self, 'offset_animation') and self.offset_animation:
                self.offset_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
                self.offset_animation.setDuration(500)
                self._begin_edit_transition(self.offset_animation)

        if hasattr(self, 'offset_animation') and self.offset_animation:
            self._start_property_animation(self.offset_animation, float(target_offset))
        
        # Update webviews after animation starts
        self.update_active_webviews()
        self.update()

    def _finalize_offset_animation(self):
        if hasattr(self, 'offset_animation') and self.offset_animation and self.offset_animation.state() == QPropertyAnimation.State.Running:
            value = self.offset_animation.currentValue()
            if value is None:
                value = self.slide_container.offset_x if self.slide_container else 0
            self.offset_animation.stop()
            if self.slide_container:
                self.slide_container.set_offset_x(float(value))

    def _start_property_animation(self, animation: QPropertyAnimation, end_value: float):
        if not animation:
            return

        target_object = animation.targetObject()
        property_name_data = animation.propertyName()
        if not property_name_data:
            return

        property_name = property_name_data.data().decode()
        current_value = None

        # If animation is running, get current value and stop it properly
        if animation.state() == QPropertyAnimation.State.Running:
            current_value = animation.currentValue()
            animation.stop()
            # Set the current value on the target object to prevent jumps
            if target_object is not None and current_value is not None:
                try:
                    target_object.setProperty(property_name, float(current_value))
                except Exception:
                    pass

        # Get current value from object if not already set
        if current_value is None and target_object is not None:
            try:
                current_value = target_object.property(property_name)
            except Exception:
                current_value = None

        if current_value is None:
            current_value = end_value

        try:
            animation.setStartValue(float(current_value))
            animation.setEndValue(float(end_value))
            animation.start()
        except Exception:
            return

        if (hasattr(self, '_active_edit_animations') and
            animation in self._active_edit_animations and
            animation.state() != QPropertyAnimation.State.Running):
            self._handle_edit_transition_animation_finished(animation)

    def _begin_edit_transition(self, *animations: QPropertyAnimation):
        self._active_edit_animations = {anim for anim in animations if anim is not None}
        self._edit_transition_active = bool(self._active_edit_animations)

    def _clear_edit_transition_guard(self):
        self._active_edit_animations.clear()
        self._edit_transition_active = False

    def _handle_edit_transition_animation_finished(self, animation: Optional[QPropertyAnimation]):
        if animation in self._active_edit_animations:
            self._active_edit_animations.discard(animation)
            if not self._active_edit_animations:
                self._clear_edit_transition_guard()
                # Show webviews after exit animation completes (not during edit mode entry)
                if not self.edit_mode and not self.card_edit_mode:
                    self.update_active_webviews()

    def _on_edit_transition_animation_finished(self):
        self._handle_edit_transition_animation_finished(self.sender())

    def update_webview_geometry(self):
        """Update geometry of the active webview to match the slide position"""
        # Don't update geometry in edit modes or during drag
        if self.edit_mode or self.card_edit_mode or self.is_dragging:
            return
            
        if not self.webview_manager.webview:
            return
            
        # Only update if we're on a webview slide and page is loaded
        if not self.webview_manager.page_loaded:
            return

        # Find current webview slide
        webview_slide_index = self.get_slide_index_for_type(SlideType.WEBVIEW)
        
        # Only update if we're currently on the webview slide
        if webview_slide_index >= 0 and webview_slide_index == self.current_slide:
             geom = self.get_embedded_card_geometry(webview_slide_index)
             
             # Use the centralized show_webview method which handles optimization
             self.webview_manager.show_webview(geom)

    def on_timeout(self):
        """ARM-optimized timer callback with dynamic interval adjustment

        Timer intervals (ARM optimization):
        - Animation mode: 16ms (60 FPS) - during slide transitions
        - Breathing mode: 33ms (30 FPS) - on clock slide for smooth colon
        - Idle mode: 1000ms (1 FPS) - on other slides, only for clock updates

        This reduces CPU usage by ~75-85% on ARM devices during idle time.
        """
        # Check if any animations are running
        has_active_animation = False
        if hasattr(self, 'offset_animation') and self.offset_animation:
            has_active_animation |= (self.offset_animation.state() == QPropertyAnimation.State.Running)
        if hasattr(self, 'scale_animation') and self.scale_animation:
            has_active_animation |= (self.scale_animation.state() == QPropertyAnimation.State.Running)
        if hasattr(self, 'offset_y_animation') and self.offset_y_animation:
            has_active_animation |= (self.offset_y_animation.state() == QPropertyAnimation.State.Running)
        if hasattr(self, 'panel_opacity_animation') and self.panel_opacity_animation:
            has_active_animation |= (self.panel_opacity_animation.state() == QPropertyAnimation.State.Running)
        if hasattr(self, 'panel_scale_animation') and self.panel_scale_animation:
            has_active_animation |= (self.panel_scale_animation.state() == QPropertyAnimation.State.Running)

        self._animation_active = has_active_animation

        # Detect if animation just finished
        prev_animation_active = getattr(self, '_prev_animation_active', False)
        if prev_animation_active and not has_active_animation:
            self.update_active_webviews()
        self._prev_animation_active = has_active_animation

        # ARM optimization: Update breathing frame counter using lookup table
        self._breathing_frame = (self._breathing_frame + 1) % 100
        # Keep legacy breathing_time for compatibility
        self.breathing_time = (self.breathing_time + self.breathing_speed) % 1.0

        # Update digit change animations
        has_digit_animation = self._update_digit_animations()

        # Check if time has changed (for clock updates)
        current_second = datetime.now().second
        time_changed = (current_second != self._last_update_second)
        if time_changed:
            self._last_update_second = current_second

        # Check if on clock slide (breathing colon needs smooth animation)
        on_clock_slide = False
        if 0 <= self.current_slide < len(self.slides):
            on_clock_slide = (self.slides[self.current_slide]['type'] == SlideType.CLOCK)

        # ARM optimization: Dynamically adjust timer interval
        desired_state = 'idle'
        if has_active_animation:
            desired_state = 'animation'
        elif on_clock_slide:
            desired_state = 'breathing'

        # Fix: Stop timer before changing interval to prevent race conditions with lock
        if desired_state != self._timer_interval_state:
            self._timer_interval_state = desired_state
            was_active = self.main_timer.isActive()

            # Atomic operation: stop, change, start
            if was_active:
                self.main_timer.stop()

            # Change interval while stopped
            if desired_state == 'animation':
                self.main_timer.setInterval(16)  # 60 FPS
            elif desired_state == 'breathing':
                self.main_timer.setInterval(33)  # 30 FPS
            else:  # idle
                self.main_timer.setInterval(1000)  # 1 FPS

            # Restart only if was active and window is visible
            if was_active and self.isVisible() and not self.isMinimized():
                self.main_timer.start()

        # Only trigger repaint if something actually changed or breathing animation is visible
        if has_active_animation or time_changed or on_clock_slide or has_digit_animation:
            self.update()
            self.update_webview_geometry()
        # If no animations, time hasn't changed, and not on clock slide, skip repaint to save CPU

    def keyPressEvent(self, event):
        """Handle key press"""
        # Reset clock return timer on user interaction
        self.reset_clock_return_timer()

        # Ignore arrow keys if modifier keys are pressed (prevents language change from triggering navigation)
        modifiers = event.modifiers()
        has_modifiers = (modifiers & (Qt.KeyboardModifier.ShiftModifier |
                                      Qt.KeyboardModifier.ControlModifier |
                                      Qt.KeyboardModifier.AltModifier |
                                      Qt.KeyboardModifier.MetaModifier))

        if event.key() == Qt.Key.Key_Escape:
            if self.card_edit_mode:
                self.exit_card_edit_mode()
            elif self.edit_mode and not self._edit_transition_active:
                self.exit_edit_mode()
        elif event.key() == Qt.Key.Key_Left and not has_modifiers:
            self.previous_slide()
        elif event.key() == Qt.Key.Key_Right and not has_modifiers:
            self.next_slide()

    def showEvent(self, event):
        """Handle show event to apply fullscreen state"""
        super().showEvent(event)
        # Ensure focus for keyboard events (fullscreen is handled in main())
        if self.is_fullscreen:
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            self.activateWindow()

        # Fix: Resume timer when window becomes visible
        if not self.main_timer.isActive():
            self.main_timer.start()

    def hideEvent(self, event):
        """Handle hide event to stop unnecessary updates"""
        super().hideEvent(event)
        # Fix: Stop timer when window is hidden to save CPU
        if self.main_timer.isActive():
            self.main_timer.stop()

    def changeEvent(self, event):
        """Handle window state changes (minimize, etc.)"""
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            # Fix: Stop timer when minimized, resume when restored
            if self.isMinimized():
                if self.main_timer.isActive():
                    self.main_timer.stop()
            elif not self.main_timer.isActive() and self.isVisible():
                self.main_timer.start()

    def resizeEvent(self, event):
        """Handle resize"""
        super().resizeEvent(event)
        self.update_scale_factor()
        self.calculate_display_parameters()
        if self.edit_panel:
            self._apply_settings_panel_geometry()

        # Update webview positions if they exist
        self.update_active_webviews()
        self._language_control_layout = None  # исправлено: пересчитываем хит-тесты после изменения размеров

        if self.edit_mode:
            target_offset_x = -self.current_slide * self.width()
            target_offset_y = -self.height() * 0.15
        else:
            target_offset_x = -self.current_slide * self.width()
            target_offset_y = 0.0

        current_offset_x = self.slide_container.get_offset_x()
        if not math.isclose(current_offset_x, target_offset_x, rel_tol=1e-4, abs_tol=0.5):
            if self.offset_animation.state() == QPropertyAnimation.State.Running:
                self.offset_animation.stop()
            self.slide_container.set_offset_x(target_offset_x)

        current_offset_y = self.slide_container.get_offset_y()
        if not math.isclose(current_offset_y, target_offset_y, rel_tol=1e-4, abs_tol=0.5):
            if self.offset_y_animation.state() == QPropertyAnimation.State.Running:
                self.offset_y_animation.stop()
            self.slide_container.set_offset_y(target_offset_y)

        if (self.offset_animation.state() != QPropertyAnimation.State.Running and
                self.scale_animation.state() != QPropertyAnimation.State.Running and
                self.offset_y_animation.state() != QPropertyAnimation.State.Running):
            self._clear_edit_transition_guard()
            
        # Resize brightness overlay
        if hasattr(self, 'brightness_overlay'):
            self.brightness_overlay.resize(self.size())
            if self.brightness_overlay.isVisible():
                self.brightness_overlay.raise_()

    def paintEvent(self, event):
        """Main paint event"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # Background
        painter.fillRect(self.rect(), self.background_color)
        
        # Apply transformations
        painter.save()
        
        center_x = self.width() // 2
        center_y = self.height() // 2
        
        scale = self.slide_container.scale
        offset_x = self.slide_container.offset_x
        offset_y = self.slide_container.offset_y
        
        painter.translate(center_x, center_y)
        painter.scale(scale, scale)

        if self.edit_mode:
            effective_offset_x = 0.0
        else:
            effective_offset_x = offset_x

        painter.translate(-center_x + effective_offset_x, -center_y + offset_y)
        
        # Draw slides
        if self.edit_mode:
            self.draw_slides_edit_mode(painter)
        else:
            self.draw_slides_normal_mode(painter)
        
        painter.restore()
        
        # Draw UI overlays
        if self.edit_mode and not self.card_edit_mode:
            self.draw_edit_mode_ui(painter)
        
        if not self.edit_mode and (not self.nav_hidden or self._nav_opacity > 0.0):
            self.draw_navigation_dots(painter)

    def draw_slides_normal_mode(self, painter: QPainter):
        """Draw slides in normal viewing mode"""
        viewport_left = -self.slide_container.offset_x
        viewport_right = viewport_left + self.width()
        
        for i, slide in enumerate(self.slides):
            x_offset = i * self.width()
            
            # Performance optimization: Culling off-screen slides
            # Skip drawing if the slide is strictly outside the viewport
            if x_offset + self.width() < viewport_left or x_offset > viewport_right:
                continue

            painter.save()
            painter.translate(x_offset, 0)

            if slide['type'] == SlideType.CLOCK:
                self.draw_clock_slide(painter)
            elif slide['type'] == SlideType.WEATHER:
                self.draw_weather_slide(painter, slide)
            elif slide['type'] == SlideType.CUSTOM:
                self.draw_custom_slide(painter, slide)
            elif slide['type'] == SlideType.WEBVIEW:
                # Draw placeholder if page hasn't loaded yet OR webview is not visible
                if not self.webview_manager.page_loaded or not (self.webview_manager.webview and self.webview_manager.webview.isVisible() and i == self.current_slide):
                    self.draw_webview_slide(painter, slide)
            elif slide['type'] == SlideType.ADD:
                self.draw_add_slide(painter)

            painter.restore()

    def draw_slides_edit_mode(self, painter: QPainter):
        """Draw slides in edit mode with animated swiping and reordering"""
        if not self.slides:
            return

        card_scale = 0.62
        card_width = int(self.width() * card_scale)
        card_height = int(self.height() * card_scale)
        start_y = max(60, int(80 * self.scale_factor))
        center_x = self.width() // 2

        width = max(1, self.width())
        focus_position = -self.slide_container.offset_x / width
        focus_index = int(round(focus_position))
        focus_index = max(0, min(focus_index, len(self.slides) - 1))

        # Draw cards in two passes: normal cards first, then dragged card on top
        for idx, slide in enumerate(self.slides):
            # Skip the dragged card in the first pass
            if self.is_reordering_card and idx == self.reorder_drag_index:
                continue

            displacement = idx * width + self.slide_container.offset_x

            # Apply any active swap animation offset
            if idx in self.reorder_card_offsets:
                displacement += self.reorder_card_offsets[idx].x()

            card_x = (center_x - card_width // 2) + displacement
            card_y = start_y

            # Skip cards that are far outside the viewport for performance
            if card_x + card_width < -width * 1.5 or card_x > width * 2.5:
                continue

            is_focus = (idx == focus_index)

            self._draw_card_at_position(painter, slide, card_x, card_y, card_width, card_height,
                                       card_scale, is_focus, elevation=0)

        # Draw the dragged card on top with elevation effect
        if self.is_reordering_card and self.reorder_drag_index is not None:
            idx = self.reorder_drag_index
            if 0 <= idx < len(self.slides):
                slide = self.slides[idx]
                displacement = idx * width + self.slide_container.offset_x
                card_x = (center_x - card_width // 2) + displacement + self.reorder_drag_offset.x()
                card_y = start_y + self.reorder_drag_offset.y()

                self._draw_card_at_position(painter, slide, card_x, card_y, card_width, card_height,
                                           card_scale, is_focus=True, elevation=8)

    def _draw_card_at_position(self, painter: QPainter, slide: dict, card_x: float, card_y: float,
                               card_width: int, card_height: int, card_scale: float,
                               is_focus: bool, elevation: int = 0):
        """Helper method to draw a single card at a specific position with optional elevation"""
        painter.save()

        # Draw shadow for elevation effect
        if elevation > 0:
            shadow_offset = elevation // 2
            shadow_blur = elevation * 2
            for i in range(shadow_blur, 0, -2):
                alpha = int(30 * (1 - i / shadow_blur))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, alpha))
                painter.drawRoundedRect(
                    int(card_x - i // 2), int(card_y - i // 2 + shadow_offset),
                    card_width + i, card_height + i, 12 + i // 4, 12 + i // 4
                )

        # Draw card border/highlight
        border_alpha = 255 if elevation > 0 else (220 if is_focus else 90)
        border_width = 3 if (elevation > 0 or is_focus) else 1
        painter.setPen(QPen(QColor(255, 255, 255, border_alpha), border_width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(int(card_x), int(card_y), card_width, card_height, 12, 12)

        # Draw drag handle hint in edit mode to show card is movable
        if (self.edit_mode and slide.get('type') != SlideType.ADD and card_width > 0 and card_height > 0):
            handle_margin_top = max(self.get_spacing(18, 10), int(card_height * 0.04))
            handle_height = max(self.get_ui_size(22, 14), int(card_height * 0.08))
            handle_width = max(int(card_width * 0.28), self.get_ui_size(120, 80))
            available_width = max(30, min(card_width - self.get_spacing(40, 24), card_width))
            handle_width = min(handle_width, available_width)
            handle_x = card_x + (card_width - handle_width) / 2
            handle_y = card_y + handle_margin_top

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 60))
            painter.drawRoundedRect(
                QRectF(handle_x, handle_y, handle_width, handle_height),
                handle_height / 2,
                handle_height / 2
            )

            dot_diameter = max(4, handle_height // 4)
            dot_radius = dot_diameter / 2
            dot_color = QColor(255, 255, 255, 170)
            columns = 3
            rows = 2
            spacing_x = handle_width / (columns + 1)
            spacing_y = handle_height / (rows + 1)

            for row in range(rows):
                for col in range(columns):
                    cx = handle_x + (col + 1) * spacing_x
                    cy = handle_y + (row + 1) * spacing_y
                    painter.setBrush(dot_color)
                    painter.drawEllipse(
                        QRectF(
                            cx - dot_radius,
                            cy - dot_radius,
                            dot_diameter,
                            dot_diameter
                        )
                    )

        # Draw slide content with opacity based on focus/elevation
        painter.save()
        painter.translate(card_x, card_y)
        painter.setClipRect(0, 0, card_width, card_height)
        painter.scale(card_scale, card_scale)
        painter.setOpacity(1.0 if (elevation > 0 or is_focus) else 0.45)

        if slide['type'] == SlideType.CLOCK:
            self.draw_clock_slide(painter)
        elif slide['type'] == SlideType.WEATHER:
            self.draw_weather_slide(painter, slide)
        elif slide['type'] == SlideType.CUSTOM:
            self.draw_custom_slide(painter, slide)
        elif slide['type'] == SlideType.WEBVIEW:
            self.draw_webview_slide(painter, slide)
        elif slide['type'] == SlideType.ADD:
            self.draw_add_slide(painter)

        painter.restore()
        painter.restore()

    def draw_clock_slide(self, painter: QPainter):
        """Draw clock slide with digit change animations"""
        now = datetime.now()
        current_time = now.strftime("%H%M")

        # Detect digit changes and start animations
        if self._last_time_string != current_time:
            for i, (old_char, new_char) in enumerate(zip(self._last_time_string.ljust(4, '0'), current_time)):
                if old_char != new_char:
                    # Start animation for this position
                    self._digit_animations[i] = {
                        'progress': 0.0,
                        'old_digit': old_char,
                        'new_digit': new_char
                    }
            self._last_time_string = current_time

        canvas_width = self.width()
        canvas_height = self.height()

        current_x = float(self.clock_left_margin)

        # Draw digits with animations
        for index, digit_char in enumerate(current_time):
            # Check if this digit is animating
            anim_data = self._digit_animations.get(index)
            self.draw_digit(painter, digit_char, current_x + self.dot_size / 2, self.time_start_y,
                          animation_data=anim_data, position=index)
            current_x += self.digit_actual_width

            if index == 0 or index == 2:
                current_x += self.inter_digit_spacing
            elif index == 1:
                colon_center_x = current_x + self.colon_gap / 2
                self.draw_colon(painter, colon_center_x, self.colon_center_y)
                current_x += self.colon_gap

        # Draw date
        self.draw_date(painter, canvas_width, canvas_height, now)

    def _get_dot_pixmap(self, radius: float, color: QColor, *, with_highlight: bool) -> QPixmap:
        radius_key = int(round(radius * 1000))
        cache_key = (radius_key, color.rgba(), with_highlight)
        pixmap = self._dot_pixmap_cache.get(cache_key)

        if pixmap is None:
            halo_padding = max(6, int(radius * 1.5))
            size = int(math.ceil(radius * 2 + halo_padding * 2))
            if size % 2:
                size += 1
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)

            temp_painter = QPainter(pixmap)
            temp_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            temp_painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            center = size / 2
            self.draw_glow_dot(temp_painter, center, center, radius, color, with_highlight=with_highlight)
            temp_painter.end()

            # Fix: Implement LRU cache limit
            if len(self._dot_pixmap_cache) >= self._dot_pixmap_cache_max_size:
                # Remove oldest 20% of entries to prevent thrashing
                remove_count = max(1, self._dot_pixmap_cache_max_size // 5)
                for _ in range(remove_count):
                    if self._dot_pixmap_cache:
                        first_key = next(iter(self._dot_pixmap_cache))
                        del self._dot_pixmap_cache[first_key]

            self._dot_pixmap_cache[cache_key] = pixmap

        return pixmap

    def draw_digit(self, painter: QPainter, digit: str, start_x: float, start_y: float,
                  animation_data: Optional[Dict[str, any]] = None, position: int = 0):
        """Draw a single digit with optional fade animation"""
        pattern = self.digit_patterns.get(digit, self.digit_patterns["0"])
        radius = self.dot_size / 2
        pixmap = self._get_dot_pixmap(radius, self._digit_color_scaled, with_highlight=True)
        half_w = pixmap.width() / 2
        half_h = pixmap.height() / 2

        if animation_data and animation_data['progress'] < 1.0:
            # Digit is animating - simple fade transition
            progress = animation_data['progress']

            # Old digit fades out (first half)
            if progress < 0.5:
                old_pattern = self.digit_patterns.get(animation_data['old_digit'], self.digit_patterns["0"])
                old_alpha = 1.0 - (progress * 2)  # Fade out in first half

                painter.save()
                painter.setOpacity(old_alpha)

                for row in range(5):
                    for col in range(3):
                        if old_pattern[row][col]:
                            x = start_x + col * self.dot_spacing
                            y = start_y + row * self.dot_spacing
                            painter.drawPixmap(int(x - half_w), int(y - half_h), pixmap)

                painter.restore()

            # New digit fades in (second half)
            if progress > 0.5:
                new_alpha = (progress - 0.5) * 2  # Fade in in second half

                painter.save()
                painter.setOpacity(new_alpha)

                for row in range(5):
                    for col in range(3):
                        if pattern[row][col]:
                            x = start_x + col * self.dot_spacing
                            y = start_y + row * self.dot_spacing
                            painter.drawPixmap(int(x - half_w), int(y - half_h), pixmap)

                painter.restore()
        else:
            # No animation - draw normally
            for row in range(5):
                for col in range(3):
                    if pattern[row][col]:
                        x = start_x + col * self.dot_spacing
                        y = start_y + row * self.dot_spacing
                        painter.drawPixmap(int(x - half_w), int(y - half_h), pixmap)

    def draw_colon(self, painter: QPainter, x: float, y: float):
        """Draw colon between hours and minutes - ARM optimized with lookup table"""
        # ARM optimization: Use pre-calculated breathing intensity from lookup table
        breathing_intensity = self._breathing_lookup[self._breathing_frame]
        
        # Use effective_brightness for stable rendering during software dimming
        brightness = self.effective_brightness

        if self.colon_color.red() > max(self.colon_color.green(), self.colon_color.blue()):
            color = QColor(
                int(self.colon_color.red() * brightness * breathing_intensity),
                int(self.colon_color.green() * brightness * breathing_intensity),
                int(self.colon_color.blue() * brightness * breathing_intensity)
            )
            dot_radius = (self.dot_size / 2) * (0.95 + 0.05 * breathing_intensity)
        else:
            color = QColor(self._colon_color_scaled)
            dot_radius = self.dot_size / 2

        vertical_offset = self.dot_spacing * 0.85
        self.draw_glow_dot(painter, x, y - vertical_offset, dot_radius, color, with_highlight=False)
        self.draw_glow_dot(painter, x, y + vertical_offset, dot_radius, color, with_highlight=False)

    def draw_glow_dot(self, painter: QPainter, x: float, y: float, radius: float,
                     color: QColor, *, with_highlight: bool = True):
        """ARM-optimized: Draw a glowing dot with full pixmap caching (матовый вид)"""
        # Use effective_brightness to maintain cache stability
        brightness = self.effective_brightness
        
        # Round radius and color for cache key (10% buckets for brightness variations - better for ARM)
        radius_rounded = int(radius)
        brightness_bucket = int(brightness * 10) / 10.0  # 10% increments - reduces cache misses
        r = int(color.red() * brightness_bucket)
        g = int(color.green() * brightness_bucket)
        b = int(color.blue() * brightness_bucket)

        # with_highlight больше не используется, убран из cache_key для инвалидации старого кэша
        cache_key = (radius_rounded, r, g, b)

        # Check cache
        if cache_key in self._glow_dot_cache:
            pixmap = self._glow_dot_cache[cache_key]
            half_size = pixmap.width() // 2
            painter.drawPixmap(int(x - half_size), int(y - half_size), pixmap)
            return

        # Not in cache - render to pixmap
        is_red = color.red() > max(color.green(), color.blue()) * 1.2

        # Calculate maximum size needed for pixmap
        if brightness > 0.3:
            halo_radius = radius * 2.0 if is_red else radius * 1.6
        else:
            halo_radius = radius

        pixmap_size = int(halo_radius * 2.5)  # Extra padding for smooth edges
        pixmap = QPixmap(pixmap_size, pixmap_size)
        pixmap.fill(Qt.GlobalColor.transparent)

        # Render to pixmap
        pix_painter = QPainter(pixmap)
        pix_painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pix_painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        pix_painter.setPen(Qt.PenStyle.NoPen)

        center_x = pixmap_size / 2
        center_y = pixmap_size / 2

        base_color = QColor(color)
        base_alpha = int(235 * brightness)
        base_color.setAlpha(base_alpha)

        # Halo
        if brightness > 0.3:
            if is_red:
                halo_alpha = int(180 * brightness)
            else:
                halo_alpha = int(120 * brightness * 0.7)

            halo_gradient = QRadialGradient(QPointF(center_x, center_y), halo_radius)
            glow_color = QColor(base_color)
            glow_color.setAlpha(halo_alpha)
            halo_gradient.setColorAt(0.0, glow_color)
            glow_color.setAlpha(0)
            halo_gradient.setColorAt(1.0, glow_color)

            pix_painter.setBrush(halo_gradient)
            pix_painter.drawEllipse(QPointF(center_x, center_y), halo_radius, halo_radius)

        # Main circle - матовый вид без глянцевого highlight
        inner_radius = radius * 0.9 if is_red else radius * 0.82
        pix_painter.setBrush(base_color)
        pix_painter.drawEllipse(QPointF(center_x, center_y), inner_radius, inner_radius)

        pix_painter.end()

        # Fix: Improved LRU cache management - remove oldest 20% when limit exceeded
        if len(self._glow_dot_cache) >= self._glow_dot_cache_max_size:
            # Remove oldest 20% of entries to prevent thrashing during resize
            remove_count = max(1, self._glow_dot_cache_max_size // 5)
            for _ in range(remove_count):
                if self._glow_dot_cache:
                    first_key = next(iter(self._glow_dot_cache))
                    del self._glow_dot_cache[first_key]

        # Add to cache
        self._glow_dot_cache[cache_key] = pixmap

        # Draw cached pixmap
        half_size = pixmap.width() // 2
        painter.drawPixmap(int(x - half_size), int(y - half_size), pixmap)

    def _get_cached_font(self, family: str, size: int) -> QFont:
        """Get cached QFont object for performance with LRU eviction"""
        cache_key = (family, size)

        if cache_key in self._font_cache:
            return self._font_cache[cache_key]

        # LRU eviction if cache is full
        if len(self._font_cache) >= self._font_cache_max_size:
            # Remove oldest entry (first key in dict - Python 3.7+ maintains insertion order)
            oldest_key = next(iter(self._font_cache))
            del self._font_cache[oldest_key]

        # Create new font
        font = QFont(family, size)
        try:
            font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferQuality)
        except AttributeError:
            font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        if hasattr(font, "setHintingPreference"):
            font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)

        self._font_cache[cache_key] = font
        return font

    def _get_cached_fontmetrics(self, family: str, size: int) -> QFontMetrics:
        """Get cached QFontMetrics object for performance with LRU eviction"""
        cache_key = (family, size)

        if cache_key in self._fontmetrics_cache:
            return self._fontmetrics_cache[cache_key]

        # LRU eviction if cache is full
        if len(self._fontmetrics_cache) >= self._fontmetrics_cache_max_size:
            oldest_key = next(iter(self._fontmetrics_cache))
            del self._fontmetrics_cache[oldest_key]

        # Create new font metrics
        font = self._get_cached_font(family, size)
        metrics = QFontMetrics(font)
        self._fontmetrics_cache[cache_key] = metrics
        return metrics

    def draw_date(self, painter: QPainter, canvas_width: int, canvas_height: int, now: datetime):
        """Draw date below clock"""
        base_font_size = getattr(self, "_date_font_size", max(18, int(self.dot_size * 0.85)))
        font = self._get_cached_font(self.font_family, base_font_size)
        painter.setFont(font)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setPen(self._date_color)

        metrics = self._get_cached_fontmetrics(self.font_family, base_font_size)
        text_height = metrics.height()
        gap = getattr(self, "_date_gap", max(2, int(self.dot_spacing * 0.14)))
        base_top = self.time_start_y + self.digit_actual_height + gap
        rect_top = int(base_top - metrics.ascent() * 0.2)
        rect_height = int(text_height + max(4, self.dot_spacing * 0.4))
        weekdays = self.WEEKDAYS.get(self.current_language, self.WEEKDAYS["EN"])
        months = self.MONTHS.get(self.current_language, self.MONTHS["EN"])

        if self.current_language == "EN":
            date_str = f"{weekdays[now.weekday()]}, {months[now.month - 1]} {now.day}, {now.year}"
        else:
            date_str = f"{weekdays[now.weekday()]}, {now.day} {months[now.month - 1]} {now.year}"

        date_rect = QRect(0, rect_top, canvas_width, canvas_height - rect_top)
        painter.drawText(date_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, date_str)

    def draw_weather_loading(self, painter: QPainter):
        """Draw loading state for weather slide"""
        content_height = int(self.height() * 0.7)
        font_size = max(14, int(content_height * 0.07))
        font = self._get_cached_font(self.font_family, font_size)
        
        color = self._scale_color_by_brightness(QColor(120, 120, 120))
        painter.setPen(color)
        painter.setFont(font)
        
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._tr("loading_weather"))

    def draw_weather_error(self, painter: QPainter, message: str):
        """Draw error state for weather slide"""
        content_height = int(self.height() * 0.7)
        font_size = max(12, int(content_height * 0.06))
        font = self._get_cached_font(self.font_family, font_size)
        
        color = self._scale_color_by_brightness(QColor(255, 100, 100))
        painter.setPen(color)
        painter.setFont(font)
        
        rect = self.rect().adjusted(20, 20, -20, -20)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, message)

    def _get_or_create_weather_icon(self, code: int, is_day: int, height: int) -> Optional[QPixmap]:
        """Get weather icon from cache or create it"""
        cache_key = (code, is_day, height)
        
        if cache_key in self._svg_weather_cache:
            return self._svg_weather_cache[cache_key]

        # Not in cache, create it
        icon_name = self.get_weather_icon_name(code, is_day)
        icon_path = self._get_weather_icon_path(icon_name)
        
        if not os.path.exists(icon_path):
            return None
            
        try:
            svg_renderer = QSvgRenderer(icon_path)
            if not svg_renderer.isValid():
                return None
                
            svg_size = svg_renderer.defaultSize()
            aspect_ratio = svg_size.width() / max(1, svg_size.height())
            icon_width = int(height * aspect_ratio)
            
            pixmap = QPixmap(icon_width, height)
            pixmap.fill(Qt.GlobalColor.transparent)
            
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            svg_renderer.render(painter, QRectF(0, 0, icon_width, height))
            painter.end()
            
            # LRU Cache management
            if len(self._svg_weather_cache) >= self._svg_weather_cache_max_size:
                # Remove a random/old item (Python dicts preserve insertion order, so iter gives oldest)
                try:
                    oldest_key = next(iter(self._svg_weather_cache))
                    del self._svg_weather_cache[oldest_key]
                except StopIteration:
                    pass
            
            self._svg_weather_cache[cache_key] = pixmap
            return pixmap
            
        except Exception as e:
            print(f"Error creating weather icon: {e}")
            return None

    def draw_weather_slide(self, painter: QPainter, slide: Optional[dict] = None):
        """Draw weather slide"""
        slide_data_source = (slide or {}).get('data') if isinstance(slide, dict) else None
        slide_data = self._ensure_weather_defaults(slide_data_source)

        if not self.weather_data or self.weather_loading:
            self.draw_weather_loading(painter)
            return

        # Draw weather content
        content_width = int(self.width() * 0.8)
        content_height = int(self.height() * 0.7)
        start_x = (self.width() - content_width) // 2
        start_y = (self.height() - content_height) // 2

        # Code
        code = self.weather_data.get('code', 0)
        is_day = self.weather_data.get('is_day', 1)
        
        current_y = start_y
        
        # Use effective_brightness for consistent rendering (same as text)
        # Hardware backlight or BrightnessOverlay handles actual dimming
        current_brightness = self.effective_brightness
        
        sections_drawn = False
        line_gap = int(content_height * 0.05)

        # Draw city name above icon
        if hasattr(self, 'location_city') and self.location_city:
            city_font_size = max(12, int(content_height * 0.055))
            city_font = self._get_cached_font(self.font_family, city_font_size)
            city_color = self._scale_color_by_brightness(QColor(150, 150, 150))
            painter.setPen(city_color)
            painter.setFont(city_font)
            city_metrics = self._get_cached_fontmetrics(self.font_family, city_font_size)
            city_height = city_metrics.height()
            city_rect = QRect(start_x, current_y, content_width, city_height)
            painter.drawText(city_rect, Qt.AlignmentFlag.AlignCenter, self.location_city)
            current_y += city_height + line_gap // 2
        
        if slide_data.get('show_icon', True):
            icon_height = max(60, int(content_height * 0.4))
            
            # Get icon (cached or created)
            cached_pixmap = self._get_or_create_weather_icon(code, is_day, icon_height)

            if cached_pixmap:
                icon_width = cached_pixmap.width()
                icon_x = start_x + (content_width - icon_width) // 2
                
                # Apply brightness to icon via opacity
                old_opacity = painter.opacity()
                painter.setOpacity(old_opacity * current_brightness)
                painter.drawPixmap(icon_x, current_y, cached_pixmap)
                painter.setOpacity(old_opacity)
            
            current_y += icon_height + line_gap
            sections_drawn = True

        if slide_data.get('show_temp', True):
            temp = self.weather_data.get('temp', 0)
            temp_font_size = max(24, int(content_height * 0.25))
            temp_font = self._get_cached_font(self.font_family, temp_font_size)
            temp_color = self.get_temperature_color(temp)
            temp_color = self._scale_color_by_brightness(temp_color)
            
            painter.setPen(temp_color)
            painter.setFont(temp_font)
            
            temp_metrics = self._get_cached_fontmetrics(self.font_family, temp_font_size)
            temp_height = temp_metrics.height()
            temp_rect = QRect(start_x, current_y, content_width, temp_height)
            painter.drawText(temp_rect, Qt.AlignmentFlag.AlignCenter, f"{temp}°C")
            
            current_y += temp_height + line_gap
            sections_drawn = True

        if slide_data.get('show_desc', True):
            desc = self.get_weather_description(code)
            desc_font_size = max(13, int(content_height * 0.065))
            desc_font = self._get_cached_font(self.font_family, desc_font_size)
            desc_color = self._scale_color_by_brightness(QColor(200, 200, 200))
            painter.setPen(desc_color)
            painter.setFont(desc_font)
            desc_metrics = self._get_cached_fontmetrics(self.font_family, desc_font_size)
            desc_height = desc_metrics.height()
            desc_rect = QRect(start_x, current_y, content_width, desc_height)
            painter.drawText(desc_rect, Qt.AlignmentFlag.AlignCenter, desc)
            current_y += desc_height + line_gap
            sections_drawn = True

        if slide_data.get('show_wind', True):
            wind_speed = self.weather_data.get('wind', 0)
            wind_text = self._tr("weather_wind", speed=wind_speed)
            wind_font_size = max(11, int(content_height * 0.05))
            wind_font = self._get_cached_font(self.font_family, wind_font_size)
            wind_color = self._scale_color_by_brightness(QColor(150, 150, 150))
            painter.setPen(wind_color)
            painter.setFont(wind_font)
            wind_metrics = self._get_cached_fontmetrics(self.font_family, wind_font_size)
            wind_height = wind_metrics.height()
            wind_rect = QRect(start_x, current_y, content_width, wind_height)
            painter.drawText(wind_rect, Qt.AlignmentFlag.AlignCenter, wind_text)
            current_y += wind_height + line_gap
            sections_drawn = True

        if not sections_drawn:
            fallback_font_size = max(14, int(content_height * 0.07))
            fallback_color = self._scale_color_by_brightness(QColor(120, 120, 120))
            painter.setPen(fallback_color)
            painter.setFont(self._get_cached_font(self.font_family, fallback_font_size))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._tr("loading_weather"))

    def get_temperature_color(self, temp: float) -> QColor:
        """Get color based on temperature"""
        if temp < 0:
            return QColor(100, 150, 255)
        elif temp < 10:
            return QColor(100, 200, 255)
        elif temp < 20:
            return QColor(100, 255, 150)
        elif temp < 25:
            return QColor(255, 255, 100)
        elif temp < 30:
            return QColor(255, 180, 80)
        else:
            return QColor(255, 100, 100)

    def get_weather_description(self, code: int) -> str:
        """Get weather description from code"""
        weather_codes = {
            0: {"RU": "Ясно", "EN": "Clear", "UA": "Ясно"},
            1: {"RU": "Преимущественно ясно", "EN": "Mainly clear", "UA": "Переважно ясно"},
            2: {"RU": "Переменная облачность", "EN": "Partly cloudy", "UA": "Мінлива хмарність"},
            3: {"RU": "Пасмурно", "EN": "Overcast", "UA": "Похмуро"},
            45: {"RU": "Туман", "EN": "Fog", "UA": "Туман"},
            48: {"RU": "Изморозь", "EN": "Depositing rime fog", "UA": "Паморозь"},
            51: {"RU": "Легкая морось", "EN": "Light drizzle", "UA": "Легка мряка"},
            53: {"RU": "Морось", "EN": "Moderate drizzle", "UA": "Мряка"},
            55: {"RU": "Сильная морось", "EN": "Dense drizzle", "UA": "Сильна мряка"},
            56: {"RU": "Ледяная морось", "EN": "Light freezing drizzle", "UA": "Крижана мряка"},
            57: {"RU": "Сильная ледяная морось", "EN": "Dense freezing drizzle", "UA": "Сильна крижана мряка"},
            61: {"RU": "Небольшой дождь", "EN": "Light rain", "UA": "Невеликий дощ"},
            63: {"RU": "Дождь", "EN": "Rain", "UA": "Дощ"},
            65: {"RU": "Сильный дождь", "EN": "Heavy rain", "UA": "Сильний дощ"},
            66: {"RU": "Ледяной дождь", "EN": "Light freezing rain", "UA": "Крижаний дощ"},
            67: {"RU": "Сильный ледяной дождь", "EN": "Heavy freezing rain", "UA": "Сильний крижаний дощ"},
            71: {"RU": "Небольшой снег", "EN": "Light snow", "UA": "Невеликий сніг"},
            73: {"RU": "Снег", "EN": "Snow", "UA": "Сніг"},
            75: {"RU": "Сильный снег", "EN": "Heavy snow", "UA": "Сильний сніг"},
            77: {"RU": "Снежные зерна", "EN": "Snow grains", "UA": "Снігові зерна"},
            80: {"RU": "Легкий ливень", "EN": "Light rain showers", "UA": "Легкий злива"},
            81: {"RU": "Ливень", "EN": "Rain showers", "UA": "Злива"},
            82: {"RU": "Сильный ливень", "EN": "Heavy rain showers", "UA": "Сильна злива"},
            85: {"RU": "Снег с дождем", "EN": "Light snow showers", "UA": "Сніг з дощем"},
            86: {"RU": "Сильный снег с дождем", "EN": "Heavy snow showers", "UA": "Сильний сніг з дощем"},
            95: {"RU": "Гроза", "EN": "Thunderstorm", "UA": "Гроза"},
            96: {"RU": "Гроза с градом", "EN": "Thunderstorm with slight hail", "UA": "Гроза з градом"},
            99: {"RU": "Гроза с сильным градом", "EN": "Thunderstorm with heavy hail", "UA": "Гроза з сильним градом"}
        }

        desc_dict = weather_codes.get(code, {"RU": "Неизвестно", "EN": "Unknown", "UA": "Невідомо"})
        return desc_dict.get(self.current_language, desc_dict["EN"])

    def get_weather_icon_name(self, code: int, is_day: int) -> str:
        """Get icon filename for weather code"""
        if code in [0, 1]:  # Clear / Mainly clear
            return "clear day.svg" if is_day else "clear night.svg"
        elif code == 2:  # Partly cloudy
            return "partly cloudy day.svg" if is_day else "partly cloudy night.svg"
        elif code in [3, 45, 48]:  # Overcast / Fog / Rime fog
            return "cloudy day.svg"
        elif code in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82]:  # Rain / Drizzle / Showers
            return "showers day.svg"
        elif code in [71, 73, 75, 77, 85, 86]:  # Snow / Snow grains / Snow showers
            return "cloudy day.svg"  # Use cloudy icon for snow
        elif code in [95, 96, 99]:  # Thunderstorm / Hail
            return "showers day.svg"
        else:
            return "no data.svg"

    def _get_weather_icon_path(self, icon_name: str) -> str:
        """Get absolute path for weather icon"""
        resources_dir = self.get_resource_dir("resources")
        icon_path = os.path.join(resources_dir, icon_name)
        
        if not os.path.exists(icon_path):
            icon_path = os.path.join(resources_dir, "no data.svg")
            
        return icon_path

    def draw_custom_slide(self, painter: QPainter, slide: dict):
        """Draw custom text slide"""
        text = slide['data'].get('text', self._tr('custom_default_text'))

        painter.setPen(self._scale_color_by_brightness(QColor(220, 220, 220)))
        font_size = max(14, int(24 * self.scale_factor))
        painter.setFont(QFont(self.font_family, font_size))

        margin = int(50 * self.scale_factor)
        text_rect = QRect(margin, margin, self.width() - 2 * margin, self.height() - 2 * margin)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)

    def draw_webview_slide(self, painter: QPainter, slide: dict):
        """Draw universal webview slide"""
        data = slide.get('data', {})
        title = data.get('title', self._tr('webview_default_title'))
        url = data.get('url', '')

        # Determine icon and color based on URL
        icon = "🌐"
        icon_color = QColor(100, 150, 255)
        
        if 'youtube.com' in url or 'youtu.be' in url:
            icon = "▶"
            icon_color = QColor(255, 0, 0)
        elif 'homeassistant' in url or ':8123' in url:
            icon = "🏠"
            icon_color = QColor(0, 153, 255)
            
        icon_color = self._scale_color_by_brightness(icon_color)

        # Draw icon
        painter.setPen(icon_color)
        icon_size = max(50, int(80 * self.scale_factor))
        icon_font_size = max(30, int(50 * self.scale_factor))
        painter.setFont(QFont(self.font_family, icon_font_size, QFont.Weight.Bold))

        icon_y = int(self.height() * 0.4)
        icon_rect = QRect(0, icon_y - icon_size // 2, self.width(), icon_size)
        painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, icon)

        # Draw title below
        painter.setPen(self._scale_color_by_brightness(QColor(240, 240, 240)))
        title_font_size = max(16, int(24 * self.scale_factor))
        painter.setFont(QFont(self.font_family, title_font_size, QFont.Weight.Bold))

        title_y = int(self.height() * 0.58)
        margin = int(30 * self.scale_factor)
        title_rect = QRect(margin, title_y, self.width() - 2 * margin, int(self.height() * 0.2))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, title)

        # Show error message if any
        if self.webview_manager.error_message:
            painter.setPen(self._scale_color_by_brightness(QColor(255, 110, 110)))
            error_font = QFont(self.font_family, max(12, int(16 * self.scale_factor)))
            painter.setFont(error_font)
            error_rect = QRect(margin, title_rect.bottom() + self.get_spacing(8, 6),
                               self.width() - 2 * margin, int(self.height() * 0.18))
            painter.drawText(error_rect,
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                             self.webview_manager.error_message)


    def draw_add_slide(self, painter: QPainter):
        """Draw add button slide"""
        painter.setPen(self._scale_color_by_brightness(QColor(150, 150, 150)))
        plus_font_size = max(28, int(40 * self.scale_factor))
        painter.setFont(QFont(self.font_family, plus_font_size, QFont.Weight.Bold))

        plus_text = "+"
        text_rect = QRect(0, 0, self.width(), self.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, plus_text)

        label_font_size = max(12, int(16 * self.scale_factor))
        painter.setFont(QFont(self.font_family, label_font_size))
        offset = int(40 * self.scale_factor)
        label_rect = QRect(0, self.height() // 2 + offset, self.width(), self.height() - (self.height() // 2 + offset))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._tr("add_card_slide_label"))

    def draw_navigation_dots(self, painter: QPainter):
        """Draw navigation dots"""
        if self._nav_opacity <= 0.0:
            return

        painter.save()
        painter.setOpacity(self._nav_opacity)

        dot_width = int(22 * self.scale_factor)
        dot_height = int(6 * self.scale_factor)
        dot_spacing = int(12 * self.scale_factor)

        total_width = len(self.slides) * dot_width + (len(self.slides) - 1) * dot_spacing
        start_x = (self.width() - total_width) // 2
        y = self.height() - int(42 * self.scale_factor)

        radius = dot_height / 2
        for i in range(len(self.slides)):
            x = start_x + i * (dot_width + dot_spacing)

            painter.setPen(Qt.PenStyle.NoPen)
            if i == self.current_slide:
                dot_color = self._scale_color_by_brightness(QColor(255, 255, 255))
                painter.setBrush(dot_color)
            else:
                dot_color = self._scale_color_by_brightness(QColor(70, 70, 70))
                painter.setBrush(dot_color)

            painter.drawRoundedRect(x, y, dot_width, dot_height, radius, radius)

        painter.restore()

    def draw_edit_mode_ui(self, painter: QPainter):
        """Draw edit mode UI elements"""
        # Fullscreen toggle button in top-right corner
        button_size = int(40 * self.scale_factor)
        button_margin = int(20 * self.scale_factor)
        button_x = self.width() - button_size - button_margin
        button_y = button_margin

        # Draw button background
        button_rect = QRectF(button_x, button_y, button_size, button_size)
        painter.setPen(Qt.PenStyle.NoPen)
        bg_color = self._scale_color_by_brightness(QColor(70, 70, 70, 180))
        painter.setBrush(bg_color)
        radius = button_size / 4
        painter.drawRoundedRect(button_rect, radius, radius)

        # Draw fullscreen icon
        icon_padding = int(10 * self.scale_factor)
        icon_x = button_x + icon_padding
        icon_y = button_y + icon_padding
        icon_size = button_size - 2 * icon_padding

        icon_color = self._scale_color_by_brightness(QColor(220, 220, 220))
        painter.setPen(QPen(icon_color, max(2, int(2 * self.scale_factor))))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self.is_fullscreen:
            # Draw "exit fullscreen" icon (arrows pointing inward)
            corner_size = icon_size // 3
            # Top-left arrow
            painter.drawLine(icon_x + corner_size, icon_y, icon_x, icon_y)
            painter.drawLine(icon_x, icon_y, icon_x, icon_y + corner_size)
            # Top-right arrow
            painter.drawLine(icon_x + icon_size - corner_size, icon_y, icon_x + icon_size, icon_y)
            painter.drawLine(icon_x + icon_size, icon_y, icon_x + icon_size, icon_y + corner_size)
            # Bottom-left arrow
            painter.drawLine(icon_x, icon_y + icon_size - corner_size, icon_x, icon_y + icon_size)
            painter.drawLine(icon_x, icon_y + icon_size, icon_x + corner_size, icon_y + icon_size)
            # Bottom-right arrow
            painter.drawLine(icon_x + icon_size, icon_y + icon_size - corner_size, icon_x + icon_size, icon_y + icon_size)
            painter.drawLine(icon_x + icon_size - corner_size, icon_y + icon_size, icon_x + icon_size, icon_y + icon_size)
        else:
            # Draw "enter fullscreen" icon (arrows pointing outward)
            corner_size = icon_size // 3
            # Top-left arrow
            painter.drawLine(icon_x, icon_y + corner_size, icon_x, icon_y)
            painter.drawLine(icon_x, icon_y, icon_x + corner_size, icon_y)
            # Top-right arrow
            painter.drawLine(icon_x + icon_size, icon_y + corner_size, icon_x + icon_size, icon_y)
            painter.drawLine(icon_x + icon_size, icon_y, icon_x + icon_size - corner_size, icon_y)
            # Bottom-left arrow
            painter.drawLine(icon_x, icon_y + icon_size - corner_size, icon_x, icon_y + icon_size)
            painter.drawLine(icon_x, icon_y + icon_size, icon_x + corner_size, icon_y + icon_size)
            # Bottom-right arrow
            painter.drawLine(icon_x + icon_size, icon_y + icon_size - corner_size, icon_x + icon_size, icon_y + icon_size)
            painter.drawLine(icon_x + icon_size, icon_y + icon_size, icon_x + icon_size - corner_size, icon_y + icon_size)

        # Hint text at top
        painter.setPen(QColor(170, 170, 170))
        hint_font_size = max(10, int(12 * self.scale_factor))
        hint_font = QFont(self.font_family, hint_font_size, QFont.Weight.Medium)
        painter.setFont(hint_font)
        hint_text = self._tr("edit_hint")
        hint_top = int(26 * self.scale_factor)
        hint_rect = QRect(0, hint_top, self.width(), self.height() - hint_top)
        painter.drawText(hint_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, hint_text)

        # Navigation dots indicator
        self.draw_edit_mode_dots(painter)
        
        # Language buttons at bottom
        self.draw_language_buttons(painter)

    def draw_edit_mode_dots(self, painter: QPainter):
        """Draw navigation dots in edit mode"""
        dot_width = int(22 * self.scale_factor)
        dot_height = int(6 * self.scale_factor)
        dot_spacing = int(12 * self.scale_factor)

        total_width = len(self.slides) * dot_width + (len(self.slides) - 1) * dot_spacing
        start_x = (self.width() - total_width) // 2
        y = self.height() - int(76 * self.scale_factor)

        # Use cached colors if available, otherwise generate (lazy init)
        if not hasattr(self, '_edit_active_dot_color'):
            self._edit_active_dot_color = self._scale_color_by_brightness(QColor(255, 255, 255))
            self._edit_inactive_dot_color = self._scale_color_by_brightness(QColor(70, 70, 70))

        radius = dot_height / 2
        painter.setPen(Qt.PenStyle.NoPen)
        
        for i in range(len(self.slides)):
            x = start_x + i * (dot_width + dot_spacing)

            if i == self.current_slide:
                painter.setBrush(self._edit_active_dot_color)
            else:
                painter.setBrush(self._edit_inactive_dot_color)

            painter.drawRoundedRect(x, y, dot_width, dot_height, radius, radius)

    def draw_language_buttons(self, painter: QPainter):
        """Draw language selection buttons and update button"""
        layout = self._compute_language_control_layout()  # исправлено: унифицируем размеры и hit-box контролов

        # Initialize cache if needed (lazy)
        if not hasattr(self, '_edit_lang_active_bg'):
             self._update_cached_colors()

        lang_font_size = self.get_ui_size(12, 10)
        painter.setFont(QFont(self.font_family, lang_font_size, QFont.Weight.Medium))
        radius = layout["button_height"] / 2

        for lang, rect in layout["language_rects"]:
            painter.setPen(Qt.PenStyle.NoPen)
            if lang == self.current_language:
                painter.setBrush(self._edit_lang_active_bg)
                text_color = self._edit_lang_active_text
            else:
                painter.setBrush(self._edit_lang_inactive_bg)
                text_color = self._edit_lang_inactive_text
                
            painter.drawRoundedRect(rect, radius, radius)
            painter.setPen(text_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, lang)

        update_rect = layout["update_rect"]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._edit_update_bg)
        painter.drawRoundedRect(update_rect, radius, radius)
        painter.setPen(self._edit_update_text)
        painter.drawText(update_rect, Qt.AlignmentFlag.AlignCenter, f"UPDATE · v{__version__}")

        autostart_rect = layout["autostart_rect"]
        autostart_enabled = AutostartManager.get_autostart_status()
        painter.setPen(Qt.PenStyle.NoPen)
        if autostart_enabled:
            painter.setBrush(self._edit_autostart_active_bg)
            text_color = self._edit_autostart_text
        else:
            painter.setBrush(self._edit_lang_inactive_bg)
            text_color = self._edit_lang_inactive_text
            
        painter.drawRoundedRect(autostart_rect, radius, radius)
        painter.setPen(text_color)
        painter.drawText(autostart_rect, Qt.AlignmentFlag.AlignCenter, self._tr("autostart_button"))

        # WiFi button
        wifi_rect = layout["wifi_rect"]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._scale_color_by_brightness(QColor(50, 120, 180, 200)))
        painter.drawRoundedRect(wifi_rect, radius, radius)
        painter.setPen(self._scale_color_by_brightness(QColor(255, 255, 255)))
        painter.drawText(wifi_rect, Qt.AlignmentFlag.AlignCenter, "WiFi")

    def save_settings(self):
        """Save settings to file"""
        settings = {
            'user_brightness': self.brightness_manager.manual_brightness,
            'digit_color': self.digit_color,
            'background_color': self.background_color,
            'colon_color': self.colon_color,
            'language': self.current_language,
            'slides': self.slides,
            'location': {'lat': self.location_lat, 'lon': self.location_lon, 'city': self.location_city},
            'fullscreen': self.is_fullscreen,
            'auto_brightness_enabled': self.brightness_manager.is_auto_enabled(),
            'auto_brightness_camera': self.brightness_manager._auto_brightness_camera_index,
            'auto_brightness_interval_ms': self.brightness_manager._auto_brightness_interval_ms,
            'auto_brightness_min': self.brightness_manager._auto_brightness_min,
            'auto_brightness_max': self.brightness_manager._auto_brightness_max,
        }
        self.settings_manager.save_settings(settings)

    def _scale_color_by_brightness(self, color: QColor) -> QColor:
        """Scales color by current effective brightness"""
        # Use effective_brightness to avoid fluctuations during software dimming
        brightness = self.effective_brightness
        
        # Optimization: if brightness is 1.0, return copy without math
        if brightness >= 0.999:
            return QColor(color)
            
        scaled = QColor(color)
        scaled.setRed(int(scaled.red() * brightness))
        scaled.setGreen(int(scaled.green() * brightness))
        scaled.setBlue(int(scaled.blue() * brightness))
        return scaled

    @property
    def user_brightness(self) -> float:
        # Возвращаем текущую системную яркость (учитывает авто-яркость и программные изменения)
        return self.brightness_manager.get_brightness()

    @property
    def effective_brightness(self) -> float:
        """
        Effective brightness for rendering.
        Always returns 1.0 (max) to disable software pixel dimming.
        - If hardware backlight exists: it handles dimming globally.
        - If no hardware backlight: BrightnessOverlay handles dimming globally.
        Pixel-level scaling causes double-dimming and performance issues.
        """
        return 1.0

    @user_brightness.setter
    def user_brightness(self, value: float):
        self.brightness_manager.set_manual_brightness(value, animate=False)

    @property
    def digit_color(self) -> QColor:
        return QColor(self._digit_color)

    @digit_color.setter
    def digit_color(self, value):
        color = value if isinstance(value, QColor) else QColor(*value)
        if self._digit_color.rgba() != color.rgba():
            self._digit_color = QColor(color)
            self._update_cached_colors()
            self.update()

    @property
    def background_color(self) -> QColor:
        return QColor(self._background_color)

    @background_color.setter
    def background_color(self, value):
        color = value if isinstance(value, QColor) else QColor(*value)
        if self._background_color.rgba() != color.rgba():
            self._background_color = QColor(color)
            self.update()

    @property
    def colon_color(self) -> QColor:
        return QColor(self._colon_color)

    @colon_color.setter
    def colon_color(self, value):
        color = value if isinstance(value, QColor) else QColor(*value)
        if self._colon_color.rgba() != color.rgba():
            self._colon_color = QColor(color)
            self._update_cached_colors()
            self.update()

    def _set_auto_brightness_controls_state(self):
        """Initialize auto-brightness controls state from saved settings."""
        if self.auto_brightness_checkbox:
            is_enabled = self.brightness_manager.is_auto_enabled()
            self.auto_brightness_checkbox.blockSignals(True)
            self.auto_brightness_checkbox.setChecked(is_enabled)
            self.auto_brightness_checkbox.blockSignals(False)
        
        if self.brightness_slider:
            self.brightness_slider.setEnabled(not self.brightness_manager.is_auto_enabled())

    def _handle_auto_brightness_checkbox(self, state):
        """Callback for auto-brightness checkbox state changes."""
        if isinstance(state, int):
            enabled = (state == 2)
        else:
            enabled = (state == Qt.CheckState.Checked)
        self.brightness_manager.set_auto_brightness_enabled(enabled, user_triggered=True)
        # Save settings to persist auto-brightness state
        self.save_settings()

    def _on_brightness_slider_changed(self, value: int):
        """Manual slider handler."""
        if self.brightness_manager.is_auto_enabled():
            return
        self.brightness_manager.set_manual_brightness(value / 100.0, animate=False)
    def _create_download_progress_popup(self, parent=None):
        """Factory to create download progress popup with consistent parenting."""
        return DownloadProgressPopup(parent or self)

    def show_notification(self, message: str, duration: int = 3000, notification_type: str = "info"):
        """Show internal notification popup"""
        # Fade out any existing notifications
        for child in self.findChildren(NotificationPopup):
            child.fade_out()

        popup = NotificationPopup(self, message, duration, notification_type)
        popup.show()

    def show_confirmation(self, title: str, message: str, on_confirm, confirm_text: str = "Yes", cancel_text: str = "No"):
        """Show internal confirmation dialog

        Args:
            title: Dialog title
            message: Dialog message
            on_confirm: Callback function to call when confirmed
            confirm_text: Text for confirm button
            cancel_text: Text for cancel button
        """
        popup = ConfirmationPopup(self, title, message, confirm_text, cancel_text)
        popup.confirmed.connect(on_confirm)
        popup.show()

    def _update_digit_animations(self) -> bool:
        """Update digit change animations, returns True if any animation is active"""
        if not self._digit_animations:
            return False

        has_active = False
        current_time = datetime.now()

        # Update all active animations
        positions_to_remove = []
        for position, anim_data in self._digit_animations.items():
            # Increment progress based on timer interval
            # At 33ms (breathing mode), increment by 33/400 = 0.0825 per frame
            # At 16ms (animation mode), increment by 16/400 = 0.04 per frame
            interval_ms = self.main_timer.interval()
            anim_data['progress'] += interval_ms / (self._digit_animation_duration * 1000)

            if anim_data['progress'] >= 1.0:
                positions_to_remove.append(position)
            else:
                has_active = True

        # Remove completed animations
        for position in positions_to_remove:
            del self._digit_animations[position]

        return has_active

    def _update_cached_colors(self):
        """ARM-optimized: Update color cache with smart invalidation"""
        # Use effective_brightness to avoid cache thrashing when using software overlay
        brightness = self.effective_brightness
        
        # Calculate new colors
        digit_scaled = QColor(self._digit_color)
        digit_scaled.setRed(int(digit_scaled.red() * brightness))
        digit_scaled.setGreen(int(digit_scaled.green() * brightness))
        digit_scaled.setBlue(int(digit_scaled.blue() * brightness))
        
        # Only clear cache if colors actually changed
        # This prevents clearing cache every frame during software brightness animations
        edit_colors_missing = not hasattr(self, '_edit_lang_active_bg')
        if digit_scaled != self._digit_color_scaled or edit_colors_missing:
            self._digit_color_scaled = digit_scaled

            colon_scaled = QColor(self._colon_color)
            colon_scaled.setRed(int(colon_scaled.red() * brightness))
            colon_scaled.setGreen(int(colon_scaled.green() * brightness))
            colon_scaled.setBlue(int(colon_scaled.blue() * brightness))
            self._colon_color_scaled = colon_scaled

            date_color = QColor(self._digit_color)
            date_color.setRed(int(date_color.red() * brightness * 0.6))
            date_color.setGreen(int(date_color.green() * brightness * 0.6))
            date_color.setBlue(int(date_color.blue() * brightness * 0.6))
            self._date_color = date_color

            # ARM optimization: Clear only digit pixmap cache, not glow dots (they use brightness buckets)
            self._dot_pixmap_cache.clear()
            # Note: _glow_dot_cache uses brightness buckets so it doesn't need to be cleared

            # Update edit mode cached colors
            self._edit_active_dot_color = self._scale_color_by_brightness(QColor(255, 255, 255))
            self._edit_inactive_dot_color = self._scale_color_by_brightness(QColor(70, 70, 70))
            
            # Cache language button colors
            self._edit_lang_active_bg = self._scale_color_by_brightness(QColor(255, 255, 255))
            self._edit_lang_active_text = self._scale_color_by_brightness(QColor(35, 35, 35))
            self._edit_lang_inactive_bg = self._scale_color_by_brightness(QColor(70, 70, 70))
            self._edit_lang_inactive_text = self._scale_color_by_brightness(QColor(220, 220, 220))
            self._edit_update_bg = self._scale_color_by_brightness(QColor(45, 45, 45))
            self._edit_update_text = self._scale_color_by_brightness(QColor(200, 200, 200))
            self._edit_autostart_active_bg = self._scale_color_by_brightness(QColor(60, 180, 100))
            self._edit_autostart_text = self._scale_color_by_brightness(QColor(255, 255, 255))



    def closeEvent(self, event):
        """Handle window close"""
        try:
            # FIRST: Save settings before any cleanup that might fail
            self.save_settings()
            
            # Fix: Graceful cleanup to prevent crashes on exit
            self._cleanup_panel_animations()
            if hasattr(self, 'edit_panel') and self.edit_panel:
                self.edit_panel.deleteLater()

            # Clean up JSON parser threads
            self._cleanup_parser_thread('location_parser_thread')
            self._cleanup_parser_thread('weather_parser_thread')

            # Stop and delete all timers
            for timer_attr in ('main_timer', 'weather_timer', 'nav_hide_timer',
                              'long_press_timer', 'clock_return_timer',
                              'update_check_timer', 'reorder_activation_timer'):
                timer = getattr(self, timer_attr, None)
                if timer:
                    timer.stop()
                    timer.deleteLater()

            # Clean up webview fade animations
            if hasattr(self, '_webview_fade_animations'):
                for anim in self._webview_fade_animations:
                    if anim.state() == QPropertyAnimation.State.Running:
                        anim.stop()
                    anim.deleteLater()
                self._webview_fade_animations.clear()

            # Clean up webviews
            self.webview_manager.cleanup()

            # Clean up brightness manager (stops ambient light monitor thread)
            if hasattr(self, 'brightness_manager') and self.brightness_manager:
                self.brightness_manager.cleanup()
        except Exception as e:
            print(f"[CloseEvent] Error during cleanup: {e}")  # Log for debugging
        finally:
            super().closeEvent(event)


