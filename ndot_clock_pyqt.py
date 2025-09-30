import sys
import math
import json
import os
from datetime import datetime
from enum import Enum
from typing import Dict, Set, Optional, Tuple

from PyQt6.QtCore import (QTimer, Qt, QPropertyAnimation, QEasingCurve,
                          pyqtSignal, QRect, QRectF, QPoint, QPointF, pyqtProperty, QUrl)
from PyQt6.QtGui import (QColor, QPainter, QRadialGradient, QFont, QFontMetrics, QMouseEvent,
                         QFontDatabase, QPen, QLinearGradient, QBrush, QPalette, QPixmap, QIcon, QAction)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QSlider, QFrame, QTextEdit, QLineEdit,
                             QCheckBox, QMessageBox, QGraphicsDropShadowEffect,
                             QColorDialog, QMenu, QGraphicsOpacityEffect)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from urllib.parse import urlencode

class SlideType(Enum):
    CLOCK = "clock"
    WEATHER = "weather"
    CUSTOM = "custom"
    YOUTUBE_MUSIC = "youtube_music"
    ADD = "add"


class AnimatedSlideContainer(QWidget):
    """Container for managing slide animations"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._offset_x = 0.0
        self._scale = 1.0
        self._offset_y = 0.0
        
    def get_offset_x(self) -> float:
        return self._offset_x
    
    def set_offset_x(self, value: float):
        self._offset_x = value
        self.update()
        self._notify_parent()
    
    def get_scale(self) -> float:
        return self._scale

    def set_scale(self, value: float):
        self._scale = value
        self.update()
        self._notify_parent()

    def get_offset_y(self) -> float:
        return self._offset_y

    def set_offset_y(self, value: float):
        self._offset_y = value
        self.update()
        self._notify_parent()

    def _notify_parent(self):
        parent = self.parentWidget()
        if parent is not None:
            parent.update()

    offset_x = pyqtProperty(float, get_offset_x, set_offset_x)
    scale = pyqtProperty(float, get_scale, set_scale)
    offset_y = pyqtProperty(float, get_offset_y, set_offset_y)


class AnimatedPanel(QFrame):
    """Panel with animation support"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._opacity = 1.0
        self._scale = 1.0
        self._opacity_effect = None

    def get_opacity(self) -> float:
        return self._opacity

    def set_opacity(self, value: float):
        self._opacity = max(0.0, min(1.0, value))
        if self._opacity_effect is None:
            self._opacity_effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(self._opacity)

    def get_scale(self) -> float:
        return self._scale

    def set_scale(self, value: float):
        self._scale = value
        # Scale is handled visually, no need to update here

    opacity = pyqtProperty(float, get_opacity, set_opacity)
    scale = pyqtProperty(float, get_scale, set_scale)


class ModernColorButton(QPushButton):
    """Color selector button with color picker dialog"""
    color_changed = pyqtSignal(QColor)

    def __init__(self, color: QColor, button_type: str = "normal", size: int = 24):
        super().__init__()
        self.current_color = color
        self.button_type = button_type
        self.setFixedSize(size, size)
        self.update_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            from PyQt6.QtWidgets import QColorDialog
            color = QColorDialog.getColor(
                self.current_color,
                self,
                "Choose Color",
                QColorDialog.ColorDialogOption.ShowAlphaChannel if self.button_type != "background" else QColorDialog.ColorDialogOption.DontUseNativeDialog
            )
            if color.isValid():
                self.current_color = color
                self.update_style()
                self.color_changed.emit(self.current_color)
        super().mousePressEvent(event)

    def update_style(self):
        size = self.width()
        radius = size // 2
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: rgb({self.current_color.red()},
                                    {self.current_color.green()},
                                    {self.current_color.blue()});
                border: 1px solid rgba(255, 255, 255, 15);
                border-radius: {radius}px;
            }}
        """)


class ModernSlider(QSlider):
    """Styled slider widget"""
    def __init__(self, orientation):
        super().__init__(orientation)
        self.setStyleSheet("""
            QSlider {
                background: transparent;
            }
            QSlider::groove:horizontal {
                border: none;
                height: 4px;
                background: rgba(255, 255, 255, 15);
                border-radius: 2px;
                margin: 10px 14px;
            }
            QSlider::sub-page:horizontal {
                background: rgba(255, 255, 255, 60);
                border-radius: 2px;
                height: 4px;
                margin: 10px 14px;
            }
            QSlider::add-page:horizontal {
                background: rgba(255, 255, 255, 15);
                border-radius: 2px;
                height: 4px;
                margin: 10px 14px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                border: none;
                width: 14px;
                height: 14px;
                margin: -11px 0;
                border-radius: 7px;
            }
        """)


class NDotClockSlider(QWidget):
    """Main clock application with slider interface"""

    WEEKDAYS = {
        "RU": ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"],
        "UA": ["понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота", "неділя"],
        "EN": ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"],
    }

    MONTHS = {
        "RU": [
            "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря"
        ],
        "UA": [
            "січня", "лютого", "березня", "квітня", "травня", "червня",
            "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"
        ],
        "EN": [
            "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
            "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"
        ],
    }

    TRANSLATIONS = {
        "EN": {
            "window_title": "N-Dot Clock Slider",
            "edit_hint": "EDIT MODE: CLICK A CARD TO MODIFY",
            "add_card_slide_label": "ADD CARD",
            "add_menu_title": "ADD CARD",
            "weather_widget_button": "Weather Widget",
            "custom_card_button": "Custom Card",
            "youtube_music_button": "YouTube Music",
            "cancel_button": "Cancel",
            "clock_editor_title": "CLOCK SETTINGS",
            "brightness_label": "BRIGHTNESS:",
            "digits_label": "DIGITS:",
            "colon_label": "COLON:",
            "background_label": "BACKGROUND:",
            "save_button": "Save",
            "weather_editor_title": "WEATHER EDITOR",
            "show_temp": "Show Temperature",
            "show_icon": "Show Icon",
            "show_desc": "Show Description",
            "show_wind": "Show Wind",
            "custom_editor_title": "CUSTOM SLIDE EDITOR",
            "youtube_music_editor_title": "YOUTUBE MUSIC EDITOR",
            "youtube_music_url_label": "YouTube Music URL:",
            "youtube_music_title_label": "Song Title:",
            "youtube_music_artist_label": "Artist:",
            "youtube_music_default_title": "Your Favorite Song",
            "youtube_music_default_artist": "Artist Name",
            "loading_weather": "Loading weather...",
            "weather_wind": "Wind: {speed:.1f} m/s",
            "custom_default_text": "New custom card",
            "delete_button": "Delete",
            "delete_confirm_title": "Delete Card",
            "delete_confirm_message": "Are you sure you want to delete this card?",
            "yes_button": "Yes",
            "no_button": "No",
        },
        "RU": {
            "window_title": "Слайдер N-Dot Clock",
            "edit_hint": "РЕЖИМ РЕДАКТИРОВАНИЯ: НАЖМИТЕ НА КАРТУ ДЛЯ ИЗМЕНЕНИЯ",
            "add_card_slide_label": "ДОБАВИТЬ КАРТУ",
            "add_menu_title": "ДОБАВИТЬ КАРТУ",
            "weather_widget_button": "Виджет погоды",
            "custom_card_button": "Пользовательская карта",
            "youtube_music_button": "YouTube Music",
            "cancel_button": "Отмена",
            "clock_editor_title": "НАСТРОЙКА ЧАСОВ",
            "brightness_label": "ЯРКОСТЬ:",
            "digits_label": "ЦИФРЫ:",
            "colon_label": "ДВОЕТОЧИЕ:",
            "background_label": "ФОН:",
            "save_button": "Сохранить",
            "weather_editor_title": "РЕДАКТОР ПОГОДЫ",
            "show_temp": "Показывать температуру",
            "show_icon": "Показывать значок",
            "show_desc": "Показывать описание",
            "show_wind": "Показывать ветер",
            "custom_editor_title": "РЕДАКТОР КАРТЫ",
            "youtube_music_editor_title": "РЕДАКТОР YOUTUBE MUSIC",
            "youtube_music_url_label": "URL YouTube Music:",
            "youtube_music_title_label": "Название песни:",
            "youtube_music_artist_label": "Исполнитель:",
            "youtube_music_default_title": "Ваша любимая песня",
            "youtube_music_default_artist": "Имя исполнителя",
            "loading_weather": "Загрузка погоды...",
            "weather_wind": "Ветер: {speed:.1f} м/с",
            "custom_default_text": "Новая пользовательская карта",
            "delete_button": "Удалить",
            "delete_confirm_title": "Удалить карту",
            "delete_confirm_message": "Вы уверены, что хотите удалить эту карту?",
            "yes_button": "Да",
            "no_button": "Нет",
        },
        "UA": {
            "window_title": "Повзунок N-Dot Clock",
            "edit_hint": "РЕЖИМ РЕДАГУВАННЯ: НАТИСНІТЬ НА КАРТКУ, ЩОБ ЗМІНИТИ",
            "add_card_slide_label": "ДОДАТИ КАРТКУ",
            "add_menu_title": "ДОДАТИ КАРТКУ",
            "weather_widget_button": "Віджет погоди",
            "custom_card_button": "Користувацька картка",
            "youtube_music_button": "YouTube Music",
            "cancel_button": "Скасувати",
            "clock_editor_title": "НАЛАШТУВАННЯ ГОДИННИКА",
            "brightness_label": "ЯСКРАВІСТЬ:",
            "digits_label": "ЦИФРИ:",
            "colon_label": "ДВОКРАПКА:",
            "background_label": "ТЛО:",
            "save_button": "Зберегти",
            "weather_editor_title": "РЕДАКТОР ПОГОДИ",
            "show_temp": "Показувати температуру",
            "show_icon": "Показувати значок",
            "show_desc": "Показувати опис",
            "show_wind": "Показувати вітер",
            "custom_editor_title": "РЕДАКТОР КАРТКИ",
            "youtube_music_editor_title": "РЕДАКТОР YOUTUBE MUSIC",
            "youtube_music_url_label": "URL YouTube Music:",
            "youtube_music_title_label": "Назва пісні:",
            "youtube_music_artist_label": "Виконавець:",
            "youtube_music_default_title": "Ваша улюблена пісня",
            "youtube_music_default_artist": "Ім'я виконавця",
            "loading_weather": "Завантаження погоди...",
            "weather_wind": "Вітер: {speed:.1f} м/с",
            "custom_default_text": "Нова користувацька картка",
            "delete_button": "Видалити",
            "delete_confirm_title": "Видалити картку",
            "delete_confirm_message": "Ви впевнені, що хочете видалити цю картку?",
            "yes_button": "Так",
            "no_button": "Ні",
        },
    }
    
    def __init__(self):
        super().__init__()
        
        # Load fonts
        self.font_family = "Arial"
        resources_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources')
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
        
        # Settings defaults
        self.settings_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                         'ndot_clock_slider_settings.json')
        self.default_settings = {
            'user_brightness': 0.8,
            'digit_color': (246, 246, 255),
            'background_color': (0, 0, 0),
            'colon_color': (220, 40, 40),
            'language': 'RU',
            'slides': [],
            'location': {'lat': None, 'lon': None}
        }

        self.setWindowTitle("ndot clock")
        self.resize(800, 480)
        self.setMinimumSize(800, 480)

        # Scaling factor for UI elements
        self.base_width = 800
        self.base_height = 480
        self.scale_factor = 1.0
        
        # Digit patterns
        self.setup_digit_patterns()
        
        # Cached state
        self._user_brightness = self.default_settings['user_brightness']
        self._digit_color = QColor(*self.default_settings['digit_color'])
        self._background_color = QColor(*self.default_settings['background_color'])
        self._colon_color = QColor(*self.default_settings['colon_color'])
        self.current_language = self.default_settings['language']
        self._digit_color_scaled = QColor(self._digit_color)
        self._colon_color_scaled = QColor(self._colon_color)
        self._date_color = QColor(self._digit_color)
        self._date_font_size = 18
        self._date_gap = 8
        self._dot_pixmap_cache: Dict[Tuple[int, int, bool], QPixmap] = {}
        
        # State
        self.current_slide = 0
        self.slides = []
        self.edit_mode = False
        self._edit_transition_active = False
        self._active_edit_animations: Set[QPropertyAnimation] = set()
        self.card_edit_mode = False
        self.current_edit_index: Optional[int] = None
        self.active_panel_type: Optional[Tuple[str, Optional[int]]] = None
        self._i18n_widgets: Dict[str, List[Tuple[object, str, Dict[str, object]]]] = {}
        self.breathing_time = 0.0
        self.breathing_speed = 0.01
        self.nav_hidden = False
        self.nav_hide_timer = QTimer(self)
        self.nav_hide_timer.timeout.connect(self.hide_navigation)
        self._edit_panel_ratios: Optional[Tuple[float, float]] = None

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
        
        # Animation container
        self.slide_container = AnimatedSlideContainer(self)
        
        # Animations
        self.offset_animation = QPropertyAnimation(self.slide_container, b"offset_x")
        self.offset_animation.setEasingCurve(QEasingCurve.Type.OutExpo)
        self.offset_animation.setDuration(1000)
        self.offset_animation.finished.connect(self._on_edit_transition_animation_finished)

        self.scale_animation = QPropertyAnimation(self.slide_container, b"scale")
        self.scale_animation.setEasingCurve(QEasingCurve.Type.OutQuart)
        self.scale_animation.setDuration(1200)
        self.scale_animation.finished.connect(self._on_edit_transition_animation_finished)

        self.offset_y_animation = QPropertyAnimation(self.slide_container, b"offset_y")
        self.offset_y_animation.setEasingCurve(QEasingCurve.Type.OutQuart)
        self.offset_y_animation.setDuration(1200)
        self.offset_y_animation.finished.connect(self._on_edit_transition_animation_finished)
        
        # Network manager for weather
        self.network_manager = QNetworkAccessManager(self)
        self.weather_data = None
        self.weather_loading = False
        self.location_lat = None
        self.location_lon = None
        self.location_loading = False
        
        # Edit panel
        self.edit_panel = None
        self.panel_animation = None
        self.panel_opacity_animation = None
        self.panel_scale_animation = None
        self._panel_opacity = 0.0
        
        # Load settings and initialize
        self.load_settings()
        self._update_cached_colors()
        self.update_scale_factor()
        self.calculate_display_parameters()
        self._apply_language()
        
        # Initialize default slides
        if not self.slides:
            self.slides = [
                {'type': SlideType.CLOCK, 'data': {}},
                {'type': SlideType.ADD, 'data': {}}
            ]
        
        # Main timer
        self.main_timer = QTimer(self)
        self.main_timer.timeout.connect(self.on_timeout)
        self.main_timer.start(16)
        
        # Weather timer
        self.weather_timer = QTimer(self)
        self.weather_timer.timeout.connect(self.fetch_weather)
        self.weather_timer.start(600000)  # 10 minutes
        self.fetch_weather()
        
        # Navigation inactivity
        self.reset_navigation_timer()

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
        """Calculate dot sizes based on window size"""
        canvas_width = max(1, self.width())
        canvas_height = max(1, self.height())
        
        base_dot_size = 44
        base_dot_spacing = 50
        base_inter_digit_spacing = 60
        
        ratio_dot = base_dot_size / base_dot_spacing
        ratio_inter = base_inter_digit_spacing / base_dot_spacing
        
        units_width = 4 * (2 + ratio_dot) + 3 * ratio_inter
        # Height units consider digits plus date spacing
        date_spacing_units = 3.0  # empirical spacing below digits for date text
        units_height = 5 + ratio_dot + date_spacing_units
        
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
        self.panel_opacity_animation.setEasingCurve(QEasingCurve.Type.OutQuart)
        self.panel_opacity_animation.setDuration(400)
        self.panel_opacity_animation.setStartValue(float(current_opacity))
        self.panel_opacity_animation.setEndValue(1.0)

        # Scale animation
        self.panel_scale_animation = QPropertyAnimation(self.edit_panel, b"scale")
        self.panel_scale_animation.setEasingCurve(QEasingCurve.Type.OutBack)
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
        self.panel_opacity_animation.setEasingCurve(QEasingCurve.Type.InQuart)
        self.panel_opacity_animation.setDuration(300)
        self.panel_opacity_animation.setStartValue(float(current_opacity))
        self.panel_opacity_animation.setEndValue(0.0)

        # Scale animation
        self.panel_scale_animation = QPropertyAnimation(self.edit_panel, b"scale")
        self.panel_scale_animation.setEasingCurve(QEasingCurve.Type.InBack)
        self.panel_scale_animation.setDuration(300)
        self.panel_scale_animation.setStartValue(float(current_scale))
        self.panel_scale_animation.setEndValue(0.8)

        if callback:
            self.panel_opacity_animation.finished.connect(callback)

        self.panel_opacity_animation.start()
        self.panel_scale_animation.start()

    def reset_navigation_timer(self):
        """Reset the navigation inactivity timer"""
        if not self.edit_mode:
            self.show_navigation()
            self.nav_hide_timer.start(10000)

    def show_navigation(self):
        """Show navigation dots"""
        if self.nav_hidden:
            self.nav_hidden = False
            self.update()

    def hide_navigation(self):
        """Hide navigation dots"""
        if not self.edit_mode and not self.nav_hidden:
            self.nav_hidden = True
            self.update()

    def fetch_location(self):
        """Fetch location from IP geolocation API"""
        if self.location_loading:
            return

        self.location_loading = True
        url = "http://ip-api.com/json/"
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Mozilla/5.0")
        reply = self.network_manager.get(request)
        reply.finished.connect(lambda: self.handle_location_response(reply))

    def handle_location_response(self, reply: QNetworkReply):
        """Handle location API response"""
        self.location_loading = False

        if reply.error() == QNetworkReply.NetworkError.NoError:
            try:
                response_data = bytes(reply.readAll()).decode()
                data = json.loads(response_data)

                # ip-api.com uses 'lat' and 'lon' keys
                self.location_lat = data.get('lat')
                self.location_lon = data.get('lon')

                if self.location_lat and self.location_lon:
                    print(f"Location detected: {self.location_lat}, {self.location_lon}")
                    # Save to settings
                    self.save_settings()
                    # Fetch weather with new location
                    self.fetch_weather()
            except Exception as e:
                print(f"Location error: {e}")
        else:
            print(f"Location request failed: {reply.errorString()}")

        reply.deleteLater()

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
        self.weather_loading = False

        if reply.error() == QNetworkReply.NetworkError.NoError:
            try:
                response_data = bytes(reply.readAll()).decode()
                data = json.loads(response_data)
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
                print(f"Weather updated: {self.weather_data['temp']}°C, code {self.weather_data['code']}")
                self.update()
            except Exception as e:
                print(f"Weather error: {e}")
        else:
            print(f"Weather request failed: {reply.errorString()}")

        reply.deleteLater()

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.card_edit_mode:
                self.exit_card_edit_mode()
            elif self.edit_mode:
                # In edit mode, only handle language button clicks
                if self.check_language_button_click(event.pos()):
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
        """Handle mouse move for dragging"""
        if self.mouse_pressed:
            delta_x = event.pos().x() - self.press_start_pos.x()
            delta_y = abs(event.pos().y() - self.press_start_pos.y())

            # Detect horizontal swipe (more horizontal than vertical)
            if abs(delta_x) > 5 and abs(delta_x) > delta_y * 2:
                if not self.is_dragging:
                    self.is_dragging = True
                    self.long_press_timer.stop()

                # Apply real-time drag offset for smooth following
                if not self.edit_mode and len(self.slides) > 1:
                    base_offset = -self.current_slide * self.width()
                    drag_factor = 0.6  # Resistance factor
                    self.drag_current_offset = base_offset + delta_x * drag_factor

                    # Apply bounds to prevent dragging too far
                    max_offset = 0
                    min_offset = -(len(self.slides) - 1) * self.width()
                    self.drag_current_offset = max(min_offset, min(max_offset, self.drag_current_offset))

                    # Update slide container directly for immediate feedback
                    if self.slide_container:
                        self.slide_container.set_offset_x(self.drag_current_offset)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.long_press_timer.stop()
            
            # Calculate total movement
            delta_x = event.pos().x() - self.press_start_pos.x()
            total_move = abs(delta_x)

            # If was dragging, handle smooth release
            if self.is_dragging and not self.edit_mode:
                # Determine if we should snap to next/previous slide
                velocity_threshold = 80  # pixels
                position_threshold = self.width() * 0.25  # 25% of screen width

                should_change_slide = (total_move > velocity_threshold or
                                     abs(delta_x) > position_threshold)

                if should_change_slide:
                    if delta_x < 0:  # Swiped left
                        self.next_slide()
                    else:  # Swiped right
                        self.previous_slide()
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
                    # First check language buttons (they have priority)
                    if self.check_language_button_click(event.pos()):
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

    def on_long_press(self):
        """Handle long press to enter edit mode"""
        if not self.edit_mode and not self._edit_transition_active:
            self.enter_edit_mode()

    def check_language_button_click(self, pos: QPoint) -> bool:
        """Check if language button was clicked"""
        if not self.edit_mode:
            return False
        
        lang_y = self.height() - 30
        lang_button_width = 50
        lang_button_height = 25
        lang_spacing = 10
        
        languages = ["RU", "EN", "UA"]
        total_width = len(languages) * lang_button_width + (len(languages) - 1) * lang_spacing
        start_x = (self.width() - total_width) // 2
        
        for i, lang in enumerate(languages):
            x = start_x + i * (lang_button_width + lang_spacing)
            if (x <= pos.x() <= x + lang_button_width and 
                lang_y <= pos.y() <= lang_y + lang_button_height):
                self.current_language = lang
                self._apply_language()
                self.save_settings()
                self.update()
                return True
        
        return False

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
            elif slide['type'] == SlideType.YOUTUBE_MUSIC:
                self.open_youtube_music_editor(self.current_slide)

            return True
        
        return False

    def show_add_menu(self):
        """Show menu to add new cards"""
        self.card_edit_mode = True
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
                border-radius: 10px;
                color: white;
                font-size: 14px;
                padding: 10px 20px;
                min-width: 120px;
                font-family: '{self.font_family}';
            }}
            QPushButton:hover {{
                background-color: #444;
                border: 2px solid #666;
            }}
        """)
        
        layout = QVBoxLayout(self.edit_panel)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 20, 30, 20)
        
        title = QLabel()
        self._register_i18n_widget(title, "add_menu_title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"font-size: 18px; font-family: '{self.font_family}';")
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

        # YouTube Music button
        youtube_btn = QPushButton()
        self._register_i18n_widget(youtube_btn, "youtube_music_button")
        youtube_btn.clicked.connect(self.add_youtube_music)
        layout.addWidget(youtube_btn)

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
        
        panel_width = 300
        panel_height = 300
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

    def save_weather_settings(self):
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

        self.save_settings()
        self.update()
        self.exit_card_edit_mode()

    def add_weather_widget(self):
        """Add weather widget card"""
        has_weather = any(s['type'] == SlideType.WEATHER for s in self.slides)
        if not has_weather:
            # Insert before the ADD card
            add_index = len(self.slides) - 1
            self.slides.insert(add_index, {'type': SlideType.WEATHER, 'data': self._default_weather_data()})
            self.current_slide = add_index
            self.save_settings()
        self.exit_card_edit_mode()

    def add_custom_card(self):
        """Add custom text card"""
        # Insert before the ADD card
        add_index = len(self.slides) - 1
        self.slides.insert(add_index, {
            'type': SlideType.CUSTOM,
            'data': {'text': self._tr('custom_default_text')}
        })
        self.current_slide = add_index
        self.save_settings()
        self.exit_card_edit_mode()
        # Open editor immediately
        self.card_edit_mode = True
        self.current_edit_index = add_index
        self._clear_i18n_widgets()
        self.setup_custom_edit_panel()

    def add_youtube_music(self):
        """Add YouTube Music card"""
        # Insert before the ADD card
        add_index = len(self.slides) - 1
        self.slides.insert(add_index, {
            'type': SlideType.YOUTUBE_MUSIC,
            'data': {
                'url': '',
                'title': self._tr('youtube_music_default_title'),
                'artist': self._tr('youtube_music_default_artist')
            }
        })
        self.current_slide = add_index
        self.save_settings()
        self.exit_card_edit_mode()
        # Open editor immediately
        self.card_edit_mode = True
        self.current_edit_index = add_index
        self._clear_i18n_widgets()
        self.setup_youtube_music_edit_panel()

    def open_clock_editor(self):
        """Open clock editor panel"""
        self.card_edit_mode = True
        self._clear_i18n_widgets()
        self.setup_clock_edit_panel()

    def open_weather_editor(self):
        """Open weather editor panel"""
        self.card_edit_mode = True
        self.current_edit_index = self.current_slide
        self._clear_i18n_widgets()
        self.setup_weather_edit_panel()

    def open_custom_editor(self, index: int):
        """Open custom slide editor"""
        self.card_edit_mode = True
        self.current_edit_index = index
        self._clear_i18n_widgets()
        self.setup_custom_edit_panel()

    def open_youtube_music_editor(self, index: int):
        """Open YouTube Music slide editor"""
        self.card_edit_mode = True
        self.current_edit_index = index
        self._clear_i18n_widgets()
        self.setup_youtube_music_edit_panel()

    def setup_clock_edit_panel(self):
        """Create clock editor panel"""
        self.active_panel_type = ("clock", None)
        _, layout = self._create_settings_panel("clock_editor_title", width_ratio=0.50, height_ratio=0.68)

        # Brightness label and slider row
        brightness_label_row = QHBoxLayout()
        brightness_label = self._settings_section_label("brightness_label")
        brightness_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        brightness_label_row.addWidget(brightness_label)
        brightness_label_row.addStretch()
        layout.addLayout(brightness_label_row)

        layout.addSpacing(self.get_spacing(6, 3))

        brightness_slider_row = QHBoxLayout()
        self.brightness_slider = ModernSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(10, 100)
        slider_width = self.get_ui_size(260, 180)
        self.brightness_slider.setFixedWidth(slider_width)
        self.brightness_slider.setValue(int(self.user_brightness * 100))
        self.brightness_slider.valueChanged.connect(lambda v: setattr(self, 'user_brightness', v / 100))
        brightness_slider_row.addWidget(self.brightness_slider)
        brightness_slider_row.addStretch()
        layout.addLayout(brightness_slider_row)

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

    def save_clock_settings(self):
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

    def save_custom_slide(self):
        """Save custom slide content"""
        if hasattr(self, 'custom_text_edit'):
            text = self.custom_text_edit.toPlainText()
            self.slides[self.current_edit_index]['data']['text'] = text
            self.save_settings()
        self.exit_card_edit_mode()

    def setup_youtube_music_edit_panel(self):
        """Create YouTube Music editor panel"""
        self.active_panel_type = ("youtube_music", self.current_edit_index)
        _, layout = self._create_settings_panel("youtube_music_editor_title", width_ratio=0.55, height_ratio=0.75)

        layout.addSpacing(self.get_spacing(8, 4))

        # URL input
        url_label = QLabel()
        self._register_i18n_widget(url_label, "youtube_music_url_label")
        url_label_font_size = self.get_ui_size(12, 10)
        url_label.setStyleSheet(f"color: #ccc; font-size: {url_label_font_size}px; font-family: '{self.font_family}';")
        layout.addWidget(url_label)

        self.youtube_url_input = QLineEdit()
        self.youtube_url_input.setText(
            self.slides[self.current_edit_index]['data'].get('url', '')
        )
        input_height = self.get_ui_size(32, 26)
        input_font_size = self.get_ui_size(12, 10)
        input_padding = self.get_ui_size(8, 6)
        input_radius = self.get_ui_size(6, 4)
        self.youtube_url_input.setMinimumHeight(input_height)
        self.youtube_url_input.setStyleSheet(f"""
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
        layout.addWidget(self.youtube_url_input)

        layout.addSpacing(self.get_spacing(12, 8))

        # Title input
        title_label = QLabel()
        self._register_i18n_widget(title_label, "youtube_music_title_label")
        title_label.setStyleSheet(f"color: #ccc; font-size: {url_label_font_size}px; font-family: '{self.font_family}';")
        layout.addWidget(title_label)

        self.youtube_title_input = QLineEdit()
        self.youtube_title_input.setText(
            self.slides[self.current_edit_index]['data'].get('title', self._tr('youtube_music_default_title'))
        )
        self.youtube_title_input.setMinimumHeight(input_height)
        self.youtube_title_input.setStyleSheet(f"""
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
        layout.addWidget(self.youtube_title_input)

        layout.addSpacing(self.get_spacing(12, 8))

        # Artist input
        artist_label = QLabel()
        self._register_i18n_widget(artist_label, "youtube_music_artist_label")
        artist_label.setStyleSheet(f"color: #ccc; font-size: {url_label_font_size}px; font-family: '{self.font_family}';")
        layout.addWidget(artist_label)

        self.youtube_artist_input = QLineEdit()
        self.youtube_artist_input.setText(
            self.slides[self.current_edit_index]['data'].get('artist', self._tr('youtube_music_default_artist'))
        )
        self.youtube_artist_input.setMinimumHeight(input_height)
        self.youtube_artist_input.setStyleSheet(f"""
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
        layout.addWidget(self.youtube_artist_input)

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
        save_btn.clicked.connect(self.save_youtube_music)
        buttons_row.addWidget(save_btn)

        buttons_row.addStretch()
        layout.addLayout(buttons_row)

    def save_youtube_music(self):
        """Save YouTube Music slide content"""
        if hasattr(self, 'youtube_url_input') and hasattr(self, 'youtube_title_input') and hasattr(self, 'youtube_artist_input'):
            url = self.youtube_url_input.text()
            title = self.youtube_title_input.text()
            artist = self.youtube_artist_input.text()
            self.slides[self.current_edit_index]['data']['url'] = url
            self.slides[self.current_edit_index]['data']['title'] = title
            self.slides[self.current_edit_index]['data']['artist'] = artist
            self.save_settings()
        self.exit_card_edit_mode()

    def confirm_delete_card(self):
        """Show confirmation dialog for deleting a card"""
        if self.current_edit_index is None or self.current_edit_index >= len(self.slides):
            return

        slide = self.slides[self.current_edit_index]
        if slide['type'] == SlideType.CLOCK:
            return  # Cannot delete clock slide

        msg = QMessageBox(self)
        msg.setWindowTitle(self._tr("delete_confirm_title"))
        msg.setText(self._tr("delete_confirm_message"))
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)

        # Apply dark theme styling
        msg.setStyleSheet(f"""
            QMessageBox {{
                background-color: rgba(30, 30, 30, 250);
                color: #f0f0f0;
                border: 2px solid rgba(255, 255, 255, 35);
                border-radius: 12px;
                font-family: '{self.font_family}';
            }}
            QMessageBox QPushButton {{
                background-color: rgba(255, 255, 255, 20);
                border: 1px solid rgba(255, 255, 255, 55);
                border-radius: 8px;
                padding: 8px 16px;
                color: #f0f0f0;
                font-weight: 500;
                min-width: 60px;
                font-family: '{self.font_family}';
            }}
            QMessageBox QPushButton:hover {{
                background-color: rgba(255, 255, 255, 35);
            }}
            QMessageBox QPushButton:default {{
                background-color: #ffffff;
                color: #151515;
                font-weight: 600;
            }}
            QMessageBox QPushButton:default:hover {{
                background-color: #e6e6e6;
            }}
        """)

        yes_button = msg.button(QMessageBox.StandardButton.Yes)
        no_button = msg.button(QMessageBox.StandardButton.No)
        if yes_button:
            yes_button.setText(self._tr("yes_button"))
        if no_button:
            no_button.setText(self._tr("no_button"))

        result = msg.exec()
        if result == QMessageBox.StandardButton.Yes:
            self.delete_current_card()

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

    def exit_card_edit_mode(self):
        """Exit card edit mode"""
        def cleanup_panel():
            self._cleanup_panel_animations()
            if self.edit_panel:
                self.edit_panel.deleteLater()
                self.edit_panel = None
            self.card_edit_mode = False
            self.active_panel_type = None
            self.current_edit_index = None
            self._clear_i18n_widgets()
            self.save_settings()
            self.update()
            self._edit_panel_ratios = None

        if self.edit_panel:
            self._animate_panel_out(cleanup_panel)
        else:
            cleanup_panel()

    def enter_edit_mode(self):
        """Enter edit mode"""
        if self.edit_mode or self._edit_transition_active:
            return

        self.edit_mode = True
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
        
        self.edit_mode = False
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

    def next_slide(self):
        """Move to next slide"""
        if len(self.slides) > 0 and self.current_slide < len(self.slides) - 1:
            if self.edit_mode:
                self._finalize_offset_animation()
            self.current_slide += 1
            self.animate_to_current_slide()
            self.reset_navigation_timer()
            self.update()

    def previous_slide(self):
        """Move to previous slide"""
        if len(self.slides) > 0 and self.current_slide > 0:
            if self.edit_mode:
                self._finalize_offset_animation()
            self.current_slide -= 1
            self.animate_to_current_slide()
            self.reset_navigation_timer()
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
                self.offset_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
                self.offset_animation.setDuration(800)
        else:
            if hasattr(self, 'offset_animation') and self.offset_animation:
                self.offset_animation.setEasingCurve(QEasingCurve.Type.OutExpo)
                self.offset_animation.setDuration(1000)
                self._begin_edit_transition(self.offset_animation)

        if hasattr(self, 'offset_animation') and self.offset_animation:
            self._start_property_animation(self.offset_animation, float(target_offset))
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

    def _on_edit_transition_animation_finished(self):
        self._handle_edit_transition_animation_finished(self.sender())

    def on_timeout(self):
        """Main timer callback"""
        self.breathing_time = (self.breathing_time + self.breathing_speed) % 1.0
        self.update()

    def keyPressEvent(self, event):
        """Handle key press"""
        if event.key() == Qt.Key.Key_Escape:
            if self.card_edit_mode:
                self.exit_card_edit_mode()
            elif self.edit_mode and not self._edit_transition_active:
                self.exit_edit_mode()
        elif event.key() == Qt.Key.Key_Left:
            self.previous_slide()
        elif event.key() == Qt.Key.Key_Right:
            self.next_slide()

    def resizeEvent(self, event):
        """Handle resize"""
        super().resizeEvent(event)
        self.update_scale_factor()
        self.calculate_display_parameters()
        if self.edit_panel:
            self._apply_settings_panel_geometry()

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

    def paintEvent(self, event):
        """Main paint event"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

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
        
        if not self.edit_mode and not self.nav_hidden:
            self.draw_navigation_dots(painter)

    def draw_slides_normal_mode(self, painter: QPainter):
        """Draw slides in normal viewing mode"""
        for i, slide in enumerate(self.slides):
            x_offset = i * self.width()
            
            painter.save()
            painter.translate(x_offset, 0)
            
            if slide['type'] == SlideType.CLOCK:
                self.draw_clock_slide(painter)
            elif slide['type'] == SlideType.WEATHER:
                self.draw_weather_slide(painter, slide)
            elif slide['type'] == SlideType.CUSTOM:
                self.draw_custom_slide(painter, slide)
            elif slide['type'] == SlideType.YOUTUBE_MUSIC:
                self.draw_youtube_music_slide(painter, slide)
            elif slide['type'] == SlideType.ADD:
                self.draw_add_slide(painter)

            painter.restore()

    def draw_slides_edit_mode(self, painter: QPainter):
        """Draw slides in edit mode with animated swiping"""
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

        for idx, slide in enumerate(self.slides):
            displacement = idx * width + self.slide_container.offset_x
            card_x = (center_x - card_width // 2) + displacement

            # Skip cards that are far outside the viewport for performance
            if card_x + card_width < -width * 1.5 or card_x > width * 2.5:
                continue

            is_focus = (idx == focus_index)

            painter.save()

            # Draw card border/highlight
            border_alpha = 220 if is_focus else 90
            border_width = 3 if is_focus else 1
            painter.setPen(QPen(QColor(255, 255, 255, border_alpha), border_width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(int(card_x), start_y, card_width, card_height, 12, 12)

            # Draw slide content with opacity based on focus
            painter.save()
            painter.translate(card_x, start_y)
            painter.setClipRect(0, 0, card_width, card_height)
            painter.scale(card_scale, card_scale)
            painter.setOpacity(1.0 if is_focus else 0.45)

            if slide['type'] == SlideType.CLOCK:
                self.draw_clock_slide(painter)
            elif slide['type'] == SlideType.WEATHER:
                self.draw_weather_slide(painter, slide)
            elif slide['type'] == SlideType.CUSTOM:
                self.draw_custom_slide(painter, slide)
            elif slide['type'] == SlideType.YOUTUBE_MUSIC:
                self.draw_youtube_music_slide(painter, slide)
            elif slide['type'] == SlideType.ADD:
                self.draw_add_slide(painter)

            painter.restore()
            painter.restore()

    def draw_clock_slide(self, painter: QPainter):
        """Draw clock slide"""
        now = datetime.now()
        current_time = now.strftime("%H%M")
        
        canvas_width = self.width()
        canvas_height = self.height()
        
        current_x = float(self.clock_left_margin)
        
        # Draw digits
        for index, digit_char in enumerate(current_time):
            self.draw_digit(painter, digit_char, current_x + self.dot_size / 2, self.time_start_y)
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
            center = size / 2
            self.draw_glow_dot(temp_painter, center, center, radius, color, with_highlight=with_highlight)
            temp_painter.end()

            self._dot_pixmap_cache[cache_key] = pixmap

        return pixmap

    def draw_digit(self, painter: QPainter, digit: str, start_x: float, start_y: float):
        """Draw a single digit"""
        pattern = self.digit_patterns.get(digit, self.digit_patterns["0"])
        radius = self.dot_size / 2
        pixmap = self._get_dot_pixmap(radius, self._digit_color_scaled, with_highlight=True)
        half_w = pixmap.width() / 2
        half_h = pixmap.height() / 2

        for row in range(5):
            for col in range(3):
                if pattern[row][col]:
                    x = start_x + col * self.dot_spacing
                    y = start_y + row * self.dot_spacing
                    painter.drawPixmap(int(x - half_w), int(y - half_h), pixmap)

    def draw_colon(self, painter: QPainter, x: float, y: float):
        """Draw colon between hours and minutes"""
        t = (math.sin(self.breathing_time * 2 * math.pi - math.pi/2) + 1) / 2
        breathing_intensity = t * t * (3 - 2 * t)
        
        if self.colon_color.red() > max(self.colon_color.green(), self.colon_color.blue()):
            color = QColor(
                int(self.colon_color.red() * self.user_brightness * breathing_intensity),
                int(self.colon_color.green() * self.user_brightness * breathing_intensity),
                int(self.colon_color.blue() * self.user_brightness * breathing_intensity)
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
        """Draw a glowing dot"""
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        
        is_red = color.red() > max(color.green(), color.blue()) * 1.2
        
        base_color = QColor(color)
        base_alpha = int(235 * self.user_brightness)
        base_color.setAlpha(base_alpha)
        
        # Halo
        if self.user_brightness > 0.3:
            if is_red:
                halo_radius = radius * 2.0
                halo_alpha = int(180 * self.user_brightness)
            else:
                halo_radius = radius * 1.6
                halo_alpha = int(120 * self.user_brightness * 0.7)
            
            halo_gradient = QRadialGradient(QPointF(x, y), halo_radius)
            glow_color = QColor(base_color)
            glow_color.setAlpha(halo_alpha)
            halo_gradient.setColorAt(0.0, glow_color)
            glow_color.setAlpha(0)
            halo_gradient.setColorAt(1.0, glow_color)
            
            painter.setBrush(halo_gradient)
            painter.drawEllipse(QPointF(x, y), halo_radius, halo_radius)
        
        # Main circle
        inner_radius = radius * 0.9 if is_red else radius * 0.82
        painter.setBrush(base_color)
        painter.drawEllipse(QPointF(x, y), inner_radius, inner_radius)
        
        # Highlight
        if with_highlight and self.user_brightness > 0.5:
            highlight_radius = inner_radius * (0.6 if is_red else 0.5)
            highlight_center = QPointF(x - inner_radius * 0.18, y - inner_radius * 0.22)
            
            highlight_brightness = min(1.0, (self.user_brightness - 0.5) * 2)
            highlight_alpha = int(180 * highlight_brightness) if is_red else int(160 * highlight_brightness)
            
            highlight_color = QColor(
                min(255, int((base_color.red() + 45) * 1.3 * highlight_brightness)),
                min(255, int((base_color.green() + 45) * highlight_brightness)),
                min(255, int((base_color.blue() + 45) * highlight_brightness)),
                highlight_alpha
            )
            
            highlight_gradient = QRadialGradient(highlight_center, highlight_radius)
            highlight_gradient.setColorAt(0.0, highlight_color)
            highlight_color.setAlpha(0)
            highlight_gradient.setColorAt(1.0, highlight_color)
            painter.setBrush(highlight_gradient)
            painter.drawEllipse(highlight_center, highlight_radius, highlight_radius)
        
        painter.restore()

    def draw_date(self, painter: QPainter, canvas_width: int, canvas_height: int, now: datetime):
        """Draw date below clock"""
        base_font_size = getattr(self, "_date_font_size", max(18, int(self.dot_size * 0.85)))
        font = QFont(self.font_family, base_font_size)
        try:
            font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferQuality)
        except AttributeError:
            font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        if hasattr(font, "setHintingPreference"):
            font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        painter.setFont(font)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setPen(self._date_color)

        metrics = QFontMetrics(font)
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

    def draw_weather_slide(self, painter: QPainter, slide: Optional[dict] = None):
        """Draw weather slide"""
        slide_data_source = (slide or {}).get('data') if isinstance(slide, dict) else None
        slide_data = self._ensure_weather_defaults(slide_data_source)

        content_width = max(1, self.width())
        content_height = max(1, self.height())
        height_scale = content_height / 480.0

        if not self.weather_data:
            loading_font_size = max(14, int(20 * height_scale))
            painter.setPen(QColor(150, 150, 150))
            painter.setFont(QFont(self.font_family, loading_font_size))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._tr("loading_weather"))
            return

        # Draw weather icon on top with original aspect ratio
        code = self.weather_data['code']
        is_day = self.weather_data.get('is_day', 1)
        icon_path = self.get_weather_icon_path(code, is_day)

        icon_height = max(80, int(content_height * 0.25))
        current_y = int(content_height * 0.12)

        if os.path.exists(icon_path):
            svg_renderer = QSvgRenderer(icon_path)
            if svg_renderer.isValid():
                # Get original SVG aspect ratio
                svg_size = svg_renderer.defaultSize()
                aspect_ratio = svg_size.width() / max(1, svg_size.height())

                # Calculate icon dimensions maintaining aspect ratio
                icon_width = int(icon_height * aspect_ratio)
                icon_x = int((content_width - icon_width) / 2)

                svg_renderer.render(painter, QRectF(icon_x, current_y, icon_width, icon_height))
                current_y += icon_height + max(12, int(content_height * 0.06))

        line_gap = max(10, int(content_height * 0.05))
        sections_drawn = False

        if slide_data.get('show_temp', True):
            temp = self.weather_data['temp']
            temp_color = self.get_temperature_color(temp)
            temp_font_size = max(28, int(content_height * 0.18))
            temp_font = QFont(self.font_family, temp_font_size, QFont.Weight.Bold)
            painter.setPen(temp_color)
            painter.setFont(temp_font)
            temp_metrics = QFontMetrics(temp_font)
            temp_height = temp_metrics.height()
            temp_rect = QRect(0, current_y, content_width, content_height - current_y)
            painter.drawText(temp_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, f"{temp}°C")
            current_y += temp_height + line_gap
            sections_drawn = True

        if slide_data.get('show_desc', True):
            desc = self.get_weather_description(code)
            desc_font_size = max(13, int(content_height * 0.065))
            desc_font = QFont(self.font_family, desc_font_size)
            painter.setPen(QColor(200, 200, 200))
            painter.setFont(desc_font)
            desc_metrics = QFontMetrics(desc_font)
            desc_height = desc_metrics.height()
            desc_rect = QRect(0, current_y, content_width, content_height - current_y)
            painter.drawText(desc_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, desc)
            current_y += desc_height + line_gap
            sections_drawn = True

        if slide_data.get('show_wind', True):
            wind_speed = self.weather_data['wind']
            wind_text = self._tr("weather_wind", speed=wind_speed)
            wind_font_size = max(11, int(content_height * 0.05))
            wind_font = QFont(self.font_family, wind_font_size)
            painter.setPen(QColor(150, 150, 150))
            painter.setFont(wind_font)
            wind_metrics = QFontMetrics(wind_font)
            wind_height = wind_metrics.height()
            wind_rect = QRect(0, current_y, content_width, content_height - current_y)
            painter.drawText(wind_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, wind_text)
            current_y += wind_height + line_gap
            sections_drawn = True

        if not sections_drawn:
            fallback_font_size = max(14, int(content_height * 0.07))
            painter.setPen(QColor(120, 120, 120))
            painter.setFont(QFont(self.font_family, fallback_font_size))
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

    def get_weather_icon_path(self, code: int, is_day: int) -> str:
        """Get SVG icon path for weather code"""
        resources_dir = os.path.join(os.path.dirname(__file__), "resources")

        # Map weather codes to icon filenames
        if code in [0, 1]:  # Clear / Mainly clear
            icon_name = "clear day.svg" if is_day else "clear night.svg"
        elif code == 2:  # Partly cloudy
            icon_name = "partly cloudy day.svg" if is_day else "partly cloudy night.svg"
        elif code in [3, 45, 48]:  # Overcast / Fog / Rime fog
            icon_name = "cloudy day.svg"
        elif code in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82]:  # Rain / Drizzle / Showers
            icon_name = "showers day.svg"
        elif code in [71, 73, 75, 77, 85, 86]:  # Snow / Snow grains / Snow showers
            icon_name = "cloudy day.svg"  # Use cloudy icon for snow
        elif code in [95, 96, 99]:  # Thunderstorm / Hail
            icon_name = "showers day.svg"
        else:
            icon_name = "no data.svg"

        icon_path = os.path.join(resources_dir, icon_name)

        # Fallback to "no data.svg" if file doesn't exist
        if not os.path.exists(icon_path):
            icon_path = os.path.join(resources_dir, "no data.svg")

        return icon_path

    def draw_custom_slide(self, painter: QPainter, slide: dict):
        """Draw custom text slide"""
        text = slide['data'].get('text', self._tr('custom_default_text'))

        painter.setPen(QColor(220, 220, 220))
        font_size = max(14, int(24 * self.scale_factor))
        painter.setFont(QFont(self.font_family, font_size))

        margin = int(50 * self.scale_factor)
        text_rect = QRect(margin, margin, self.width() - 2 * margin, self.height() - 2 * margin)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)

    def draw_youtube_music_slide(self, painter: QPainter, slide: dict):
        """Draw YouTube Music slide"""
        data = slide.get('data', {})
        title = data.get('title', self._tr('youtube_music_default_title'))
        artist = data.get('artist', self._tr('youtube_music_default_artist'))

        # Draw YouTube Music icon/logo
        painter.setPen(QColor(255, 0, 0))
        icon_size = max(40, int(60 * self.scale_factor))
        icon_font_size = max(20, int(30 * self.scale_factor))
        painter.setFont(QFont(self.font_family, icon_font_size, QFont.Weight.Bold))

        icon_y = int(self.height() * 0.3)
        icon_rect = QRect(0, icon_y - icon_size // 2, self.width(), icon_size)
        painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, "▶")

        # Draw song title
        painter.setPen(QColor(240, 240, 240))
        title_font_size = max(14, int(22 * self.scale_factor))
        painter.setFont(QFont(self.font_family, title_font_size, QFont.Weight.Bold))

        title_y = int(self.height() * 0.5)
        margin = int(30 * self.scale_factor)
        title_rect = QRect(margin, title_y, self.width() - 2 * margin, int(self.height() * 0.15))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, title)

        # Draw artist name
        painter.setPen(QColor(180, 180, 180))
        artist_font_size = max(12, int(16 * self.scale_factor))
        painter.setFont(QFont(self.font_family, artist_font_size))

        artist_y = title_y + int(self.height() * 0.15) + int(10 * self.scale_factor)
        artist_rect = QRect(margin, artist_y, self.width() - 2 * margin, int(self.height() * 0.1))
        painter.drawText(artist_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, artist)

    def draw_add_slide(self, painter: QPainter):
        """Draw add button slide"""
        painter.setPen(QColor(150, 150, 150))
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
                painter.setBrush(QColor(255, 255, 255))
            else:
                painter.setBrush(QColor(70, 70, 70))

            painter.drawRoundedRect(x, y, dot_width, dot_height, radius, radius)

    def draw_edit_mode_ui(self, painter: QPainter):
        """Draw edit mode UI elements"""
        # Hint text at top
        painter.setPen(QColor(170, 170, 170))
        hint_font_size = max(10, int(12 * self.scale_factor))
        hint_font = QFont(self.font_family, hint_font_size, QFont.Weight.Medium)
        painter.setFont(hint_font)
        hint_text = self._tr("edit_hint")
        hint_top = int(26 * self.scale_factor)
        hint_rect = QRect(0, hint_top, self.width(), self.height() - hint_top)
        painter.drawText(hint_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, hint_text)

        # Navigation arrows for multiple cards
        if len(self.slides) > 1:
            arrow_y = self.height() // 2
            arrow_size = int(20 * self.scale_factor)
            pen_width = max(2, int(3 * self.scale_factor))

            # Left arrow
            if self.current_slide > 0:
                painter.setPen(QPen(QColor(200, 200, 200), pen_width))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                left_arrow_x = int(30 * self.scale_factor)
                # Draw left arrow triangle
                points = [
                    QPoint(left_arrow_x + arrow_size, arrow_y - arrow_size),
                    QPoint(left_arrow_x, arrow_y),
                    QPoint(left_arrow_x + arrow_size, arrow_y + arrow_size)
                ]
                painter.drawPolyline(*points)

                # Card counter on left
                counter_font_size = max(10, int(12 * self.scale_factor))
                painter.setFont(QFont(self.font_family, counter_font_size))
                counter_text = f"{self.current_slide + 1}/{len(self.slides)}"
                counter_offset = int(40 * self.scale_factor)
                counter_width = int(60 * self.scale_factor)
                counter_height = int(20 * self.scale_factor)
                painter.drawText(left_arrow_x - 10, arrow_y + counter_offset, counter_width, counter_height,
                               Qt.AlignmentFlag.AlignCenter, counter_text)

            # Right arrow
            if self.current_slide < len(self.slides) - 1:
                painter.setPen(QPen(QColor(200, 200, 200), pen_width))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                right_arrow_x = self.width() - int(30 * self.scale_factor)
                # Draw right arrow triangle
                points = [
                    QPoint(right_arrow_x - arrow_size, arrow_y - arrow_size),
                    QPoint(right_arrow_x, arrow_y),
                    QPoint(right_arrow_x - arrow_size, arrow_y + arrow_size)
                ]
                painter.drawPolyline(*points)
        
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

        radius = dot_height / 2
        for i in range(len(self.slides)):
            x = start_x + i * (dot_width + dot_spacing)

            painter.setPen(Qt.PenStyle.NoPen)
            if i == self.current_slide:
                painter.setBrush(QColor(255, 255, 255))
            else:
                painter.setBrush(QColor(70, 70, 70))

            painter.drawRoundedRect(x, y, dot_width, dot_height, radius, radius)

    def draw_language_buttons(self, painter: QPainter):
        """Draw language selection buttons"""
        lang_y = self.height() - int(34 * self.scale_factor)
        lang_button_width = int(54 * self.scale_factor)
        lang_button_height = int(24 * self.scale_factor)
        lang_spacing = int(12 * self.scale_factor)

        languages = ["RU", "EN", "UA"]
        total_width = len(languages) * lang_button_width + (len(languages) - 1) * lang_spacing
        start_x = (self.width() - total_width) // 2

        lang_font_size = max(8, int(10 * self.scale_factor))
        painter.setFont(QFont(self.font_family, lang_font_size, QFont.Weight.Medium))

        radius = lang_button_height / 2
        for i, lang in enumerate(languages):
            x = start_x + i * (lang_button_width + lang_spacing)

            rect = QRectF(x, lang_y, lang_button_width, lang_button_height)
            painter.setPen(Qt.PenStyle.NoPen)

            if lang == self.current_language:
                painter.setBrush(QColor(255, 255, 255))
                text_color = QColor(35, 35, 35)
            else:
                painter.setBrush(QColor(70, 70, 70))
                text_color = QColor(220, 220, 220)

            painter.drawRoundedRect(rect, radius, radius)

            painter.setPen(text_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, lang)

    def save_settings(self):
        """Save settings to file"""
        settings = {
            'user_brightness': self.user_brightness,
            'digit_color': (self.digit_color.red(), self.digit_color.green(), self.digit_color.blue()),
            'background_color': (self.background_color.red(), self.background_color.green(),
                               self.background_color.blue()),
            'colon_color': (self.colon_color.red(), self.colon_color.green(), self.colon_color.blue()),
            'language': self.current_language,
            'slides': [{'type': s['type'].value, 'data': s['data']} for s in self.slides],
            'location': {'lat': self.location_lat, 'lon': self.location_lon}
        }
        
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f'Failed to save settings: {e}')

    def load_settings(self):
        """Load settings from file"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                
                self.user_brightness = settings.get('user_brightness', 0.8)
                
                digit_color = settings.get('digit_color', (246, 246, 255))
                self.digit_color = QColor(*digit_color)
                
                bg_color = settings.get('background_color', (0, 0, 0))
                self.background_color = QColor(*bg_color)
                
                colon_color = settings.get('colon_color', (220, 40, 40))
                self.colon_color = QColor(*colon_color)
                
                self.current_language = settings.get('language', 'RU')

                # Load location
                location = settings.get('location', {'lat': None, 'lon': None})
                self.location_lat = location.get('lat')
                self.location_lon = location.get('lon')

                slides_data = settings.get('slides', [])
                self.slides = []
                for s in slides_data:
                    self.slides.append({
                        'type': SlideType(s['type']),
                        'data': s.get('data', {})
                    })
            else:
                self.user_brightness = 0.8
                self.digit_color = QColor(246, 246, 255)
                self.background_color = QColor(0, 0, 0)
                self.colon_color = QColor(220, 40, 40)
                self.current_language = 'RU'
                self.slides = []
        except Exception as e:
            print(f'Failed to load settings: {e}')
            self.user_brightness = 0.8
            self.digit_color = QColor(246, 246, 255)
            self.background_color = QColor(0, 0, 0)
            self.colon_color = QColor(220, 40, 40)
            self.current_language = 'RU'
            self.slides = []

    @property
    def user_brightness(self) -> float:
        return self._user_brightness

    @user_brightness.setter
    def user_brightness(self, value: float):
        clamped = max(0.0, min(1.0, float(value)))
        if not math.isclose(clamped, self._user_brightness, rel_tol=1e-3):
            self._user_brightness = clamped
            self._update_cached_colors()
            self.update()

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

    def _update_cached_colors(self):
        digit_scaled = QColor(self._digit_color)
        digit_scaled.setRed(int(digit_scaled.red() * self._user_brightness))
        digit_scaled.setGreen(int(digit_scaled.green() * self._user_brightness))
        digit_scaled.setBlue(int(digit_scaled.blue() * self._user_brightness))
        self._digit_color_scaled = digit_scaled

        colon_scaled = QColor(self._colon_color)
        colon_scaled.setRed(int(colon_scaled.red() * self._user_brightness))
        colon_scaled.setGreen(int(colon_scaled.green() * self._user_brightness))
        colon_scaled.setBlue(int(colon_scaled.blue() * self._user_brightness))
        self._colon_color_scaled = colon_scaled

        date_color = QColor(self._digit_color)
        date_color.setRed(int(date_color.red() * self._user_brightness * 0.6))
        date_color.setGreen(int(date_color.green() * self._user_brightness * 0.6))
        date_color.setBlue(int(date_color.blue() * self._user_brightness * 0.6))
        self._date_color = date_color
        self._dot_pixmap_cache.clear()

    def closeEvent(self, event):
        """Handle window close"""
        self._cleanup_panel_animations()
        if hasattr(self, 'edit_panel') and self.edit_panel:
            self.edit_panel.deleteLater()
        self.save_settings()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    clock = NDotClockSlider()
    clock.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
