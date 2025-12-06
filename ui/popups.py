"""Reusable popup widgets used across the application."""

import os
import subprocess
import threading
from PyQt6.QtCore import QEasingCurve, Qt, QPropertyAnimation, QTimer, pyqtSignal, QThread, pyqtSlot, QSize
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
    QScrollArea,
)


def _get_icon_path(name: str) -> str:
    """Get path to icon file"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "resources", "icons", f"{name}.svg")


def _load_svg_icon(name: str, size: int = 24, color: str = "#ffffff") -> QIcon:
    """Load SVG icon and colorize it"""
    path = _get_icon_path(name)
    if not os.path.exists(path):
        return QIcon()
    
    renderer = QSvgRenderer(path)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(color))
    painter.end()
    
    return QIcon(pixmap)


class NotificationPopup(QWidget):
    """Modern notification popup that appears inside the app"""

    def __init__(self, parent, message: str, duration: int = 3000, notification_type: str = "info"):
        super().__init__(parent)
        # Don't use Tool flag - keep it as a child widget
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # Raise to top of parent's children
        self.raise_()

        self.message = message
        self.notification_type = notification_type  # "info", "success", "warning", "error"

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        self.card = QFrame(self)  # исправлено: оформляем уведомление в едином карточном стиле
        self.card.setObjectName("notificationCard")
        card_layout = QHBoxLayout(self.card)
        card_layout.setContentsMargins(16, 14, 18, 14)
        card_layout.setSpacing(12)

        self.icon_label = QLabel()
        self.icon_label.setObjectName("notificationIcon")
        card_layout.addWidget(self.icon_label, alignment=Qt.AlignmentFlag.AlignTop)

        self.label = QLabel(message)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        card_layout.addWidget(self.label)

        outer_layout.addWidget(self.card)

        # Style based on type
        self.update_style()

        # Fade in animation
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.fade_animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_animation.setDuration(250)
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        # Auto-hide timer
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.fade_out)
        self.hide_timer.start(duration)

    def update_style(self):
        """Update style based on notification type - dark matte backgrounds"""
        colors = {
            "info": ("#272727", "#7ad0ff", "#f0f0f0"),
            "success": ("#1f3627", "#3ec57a", "#deffe8"),
            "warning": ("#372b1c", "#f6c455", "#ffe8bb"),
            "error": ("#3a1f23", "#ff6b6b", "#ffd6d6"),
        }

        bg_color, accent_color, text_color = colors.get(self.notification_type, colors["info"])

        self.card.setStyleSheet(
            f"""
            QFrame#notificationCard {{
                background-color: {bg_color};
                border-radius: 14px;
                border: 1px solid rgba(255, 255, 255, 25);
            }}
            QLabel#notificationIcon {{
                color: {accent_color};
                font-size: 18px;
                font-weight: 600;
            }}
            QLabel {{
                color: {text_color};
                font-size: 14px;
                font-weight: 500;
                background: transparent;
            }}
        """
        )

        icons = {
            "info": "ℹ",
            "success": "✔",
            "warning": "⚠",
            "error": "⨯",
        }
        self.icon_label.setText(icons.get(self.notification_type, "ℹ"))

    def showEvent(self, event):
        """Position popup as card in the top-right corner"""
        super().showEvent(event)
        if self.parent():
            parent_rect = self.parent().rect()
            margin = 24
            max_width = min(380, int(parent_rect.width() * 0.45))
            self.card.setMinimumWidth(max_width)
            self.card.setMaximumWidth(max_width)
            preferred_height = self.card.sizeHint().height()
            self.resize(max_width, preferred_height)  # исправлено: фиксируем габариты всплывающей карточки
            x = parent_rect.width() - self.width() - margin
            y = margin
            self.move(x, y)
            self.fade_animation.start()

    def fade_out(self):
        """Fade out and close"""
        if self.hide_timer.isActive():
            self.hide_timer.stop()

        fade_out_anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        fade_out_anim.setDuration(220)
        fade_out_anim.setStartValue(1.0)
        fade_out_anim.setEndValue(0.0)
        fade_out_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        fade_out_anim.finished.connect(self.close)
        # Keep reference to prevent garbage collection
        self._fade_out_anim = fade_out_anim
        fade_out_anim.start()


class DownloadProgressPopup(QWidget):
    """Download progress window with animation"""

    def __init__(self, parent):
        super().__init__(parent)
        # Don't use Tool flag - keep it as a child widget
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Raise to top of parent's children
        self.raise_()

        # Semi-transparent background overlay
        self.overlay = QWidget(self)
        self.overlay.setStyleSheet("background-color: rgba(0, 0, 0, 180);")

        # Main container
        container = QFrame(self)
        container.setStyleSheet("""
            QFrame {
                background-color: rgba(40, 40, 40, 250);
                border-radius: 20px;
                border: none;
            }
        """)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(40, 35, 40, 35)
        layout.setSpacing(25)

        # Title
        title_label = QLabel("Downloading Update")
        title_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 20px;
                font-weight: bold;
                background: transparent;
            }
        """)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # Progress bar
        self.progress_bar = QSlider(Qt.Orientation.Horizontal)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setEnabled(False)
        self.progress_bar.setStyleSheet("""
            QSlider {
                background: transparent;
            }
            QSlider::groove:horizontal {
                border: none;
                height: 8px;
                background: rgba(255, 255, 255, 20);
                border-radius: 4px;
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(60, 180, 100, 255),
                    stop:1 rgba(80, 200, 120, 255));
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                width: 0px;
            }
        """)
        layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("Preparing download...")
        self.status_label.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 180);
                font-size: 14px;
                background: transparent;
            }
        """)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        self.container = container
        self.container.setFixedWidth(450)

    def showEvent(self, event):
        """Position popup at center of parent"""
        super().showEvent(event)
        if self.parent():
            parent_rect = self.parent().rect()
            self.overlay.setGeometry(parent_rect)
            self.container.adjustSize()
            x = (parent_rect.width() - self.container.width()) // 2
            y = (parent_rect.height() - self.container.height()) // 2
            self.container.move(x, y)
            self.setGeometry(parent_rect)

    def set_progress(self, value: int):
        """Update progress bar value (0-100)"""
        self.progress_bar.setValue(value)

    def set_status(self, text: str):
        """Update status text"""
        self.status_label.setText(text)


class ConfirmationPopup(QWidget):
    """Modern confirmation dialog inside the app"""

    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, parent, title: str, message: str, confirm_text: str = "Yes", cancel_text: str = "No"):
        super().__init__(parent)
        # Don't use Tool flag - keep it as a child widget
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Raise to top of parent's children
        self.raise_()

        # Semi-transparent background overlay
        self.overlay = QWidget(self)
        self.overlay.setStyleSheet("background-color: rgba(0, 0, 0, 150);")

        # Main dialog container
        container = QFrame(self)
        container.setStyleSheet("""
            QFrame {
                background-color: rgba(40, 40, 40, 240);
                border-radius: 16px;
                border: none;
            }
        """)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(20)

        # Title
        title_label = QLabel(title)
        title_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 18px;
                font-weight: bold;
                background: transparent;
            }
        """)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # Message
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 200);
                font-size: 14px;
                background: transparent;
            }
        """)
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message_label)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)

        self.cancel_btn = QPushButton(cancel_text)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(70, 70, 70, 255);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 30px;
                font-size: 14px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: rgba(90, 90, 90, 255);
            }
            QPushButton:pressed {
                background-color: rgba(60, 60, 60, 255);
            }
        """)
        self.cancel_btn.clicked.connect(self.on_cancel)
        button_layout.addWidget(self.cancel_btn)

        self.confirm_btn = QPushButton(confirm_text)
        self.confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(220, 60, 60, 255);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 30px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(240, 80, 80, 255);
            }
            QPushButton:pressed {
                background-color: rgba(200, 50, 50, 255);
            }
        """)
        self.confirm_btn.clicked.connect(self.on_confirm)
        button_layout.addWidget(self.confirm_btn)

        layout.addLayout(button_layout)

        self.container = container
        self.container.setFixedWidth(400)

        # Fade in animation
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.fade_animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_animation.setDuration(200)
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

    def showEvent(self, event):
        """Position popup at center of parent"""
        super().showEvent(event)
        if self.parent():
            parent_rect = self.parent().rect()

            # Overlay covers entire parent
            self.overlay.setGeometry(parent_rect)

            # Center the container
            self.container.adjustSize()
            x = (parent_rect.width() - self.container.width()) // 2
            y = (parent_rect.height() - self.container.height()) // 2
            self.container.move(x, y)

            # Make popup cover entire parent for overlay effect
            self.setGeometry(parent_rect)

            self.fade_animation.start()

    def on_confirm(self, checked=False):
        """Handle confirm button"""
        self.confirmed.emit()
        self.close()

    def on_cancel(self, checked=False):
        """Handle cancel button"""
        self.cancelled.emit()
        self.close()


class WiFiScanThread(QThread):
    """Thread for scanning WiFi networks"""
    networks_found = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    
    def run(self):
        try:
            # Rescan networks
            subprocess.run(['sudo', 'nmcli', 'device', 'wifi', 'rescan'], 
                         capture_output=True, timeout=10)
            
            # Get list of networks
            result = subprocess.run(
                ['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY,IN-USE', 'device', 'wifi', 'list'],
                capture_output=True, text=True, timeout=15
            )
            
            networks = []
            seen_ssids = set()
            
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = line.split(':')
                if len(parts) >= 3:
                    ssid = parts[0].strip()
                    if not ssid or ssid in seen_ssids:
                        continue
                    seen_ssids.add(ssid)
                    
                    signal = int(parts[1]) if parts[1].isdigit() else 0
                    security = parts[2] if len(parts) > 2 else ""
                    in_use = parts[3] == '*' if len(parts) > 3 else False
                    
                    networks.append({
                        'ssid': ssid,
                        'signal': signal,
                        'security': security,
                        'connected': in_use
                    })
            
            # Sort by signal strength
            networks.sort(key=lambda x: (-x['connected'], -x['signal']))
            self.networks_found.emit(networks)
            
        except subprocess.TimeoutExpired:
            self.error_occurred.emit("Scan timeout")
        except Exception as e:
            self.error_occurred.emit(str(e))


class WiFiConnectThread(QThread):
    """Thread for connecting to WiFi"""
    connection_result = pyqtSignal(bool, str)
    
    def __init__(self, ssid: str, password: str = ""):
        super().__init__()
        self.ssid = ssid
        self.password = password
    
    def run(self):
        try:
            if self.password:
                result = subprocess.run(
                    ['sudo', 'nmcli', 'device', 'wifi', 'connect', self.ssid, 'password', self.password],
                    capture_output=True, text=True, timeout=30
                )
            else:
                result = subprocess.run(
                    ['sudo', 'nmcli', 'device', 'wifi', 'connect', self.ssid],
                    capture_output=True, text=True, timeout=30
                )
            
            if result.returncode == 0:
                self.connection_result.emit(True, f"Connected to {self.ssid}")
            else:
                error = result.stderr.strip() or result.stdout.strip() or "Connection failed"
                self.connection_result.emit(False, error)
                
        except subprocess.TimeoutExpired:
            self.connection_result.emit(False, "Connection timeout")
        except Exception as e:
            self.connection_result.emit(False, str(e))


class OnScreenKeyboard(QFrame):
    """On-screen keyboard widget for touch input"""
    
    key_pressed = pyqtSignal(str)
    enter_pressed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.shift_active = False
        self.symbols_mode = False
        
        self.setStyleSheet("""
            OnScreenKeyboard {
                background-color: #1a1a1a;
                border-top: 1px solid #333333;
            }
        """)
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(6, 10, 6, 10)
        self.main_layout.setSpacing(6)
        
        # Keyboard layouts - fewer keys per row for larger buttons
        self.letters_lower = [
            ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
            ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
            ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', 'BACK'],
            ['SHIFT', 'z', 'x', 'c', 'v', 'b', 'n', 'm', '.', 'ENTER']
        ]
        
        self.letters_upper = [
            ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
            ['Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
            ['A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', 'BACK'],
            ['SHIFT', 'Z', 'X', 'C', 'V', 'B', 'N', 'M', '.', 'ENTER']
        ]
        
        self.symbols = [
            ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
            ['!', '@', '#', '$', '%', '^', '&', '*', '(', ')'],
            ['-', '_', '=', '+', '/', '\\', ':', ';', '"', 'BACK'],
            ['ABC', '<', '>', ',', '.', '?', '!', '@', '#', 'ENTER']
        ]
        
        self._build_keyboard(self.letters_lower)
    
    def _build_keyboard(self, keys):
        """Build keyboard UI"""
        # Clear existing layout
        while self.main_layout.count():
            item = self.main_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
        
        for row_keys in keys:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(3)
            
            for key in row_keys:
                btn = self._create_key_button(key)
                row_layout.addWidget(btn)
            
            self.main_layout.addWidget(row_widget)
    
    def _clear_layout(self, layout):
        """Recursively clear a layout"""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
    
    def _create_key_button(self, key):
        """Create a single key button"""
        btn = QPushButton()
        btn.setFixedHeight(48)
        btn.setSizePolicy(btn.sizePolicy().horizontalPolicy(), btn.sizePolicy().verticalPolicy())
        
        base_style = """
            QPushButton {
                background-color: #4a4a4a;
                border: 1px solid #5a5a5a;
                border-radius: 6px;
                color: white;
                font-size: 20px;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton:pressed {
                background-color: #6a6a6a;
            }
        """
        
        special_style = """
            QPushButton {
                background-color: #3a3a3a;
                border: 1px solid #4a4a4a;
                border-radius: 6px;
                color: white;
                font-size: 12px;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton:pressed {
                background-color: #5a5a5a;
            }
        """
        
        enter_style = """
            QPushButton {
                background-color: #2563eb;
                border: none;
                border-radius: 6px;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton:pressed {
                background-color: #3b82f6;
            }
        """
        
        if key == 'SHIFT':
            btn.setIcon(_load_svg_icon("shift", 24, "#ffffff"))
            btn.setIconSize(QSize(24, 24))
            btn.setStyleSheet(special_style)
        elif key == 'BACK':
            btn.setIcon(_load_svg_icon("backspace", 24, "#ffffff"))
            btn.setIconSize(QSize(24, 24))
            btn.setStyleSheet(special_style)
        elif key == 'ENTER':
            btn.setText("OK")
            btn.setStyleSheet(enter_style)
        elif key == 'ABC':
            btn.setText("ABC")
            btn.setStyleSheet(special_style)
        else:
            btn.setText(key)
            btn.setStyleSheet(base_style)
        
        btn.clicked.connect(lambda checked, k=key: self._on_key_click(k))
        return btn
    
    def _on_key_click(self, key):
        """Handle key press"""
        if key == 'SHIFT':
            self.shift_active = not self.shift_active
            if self.shift_active:
                self._build_keyboard(self.letters_upper)
            else:
                self._build_keyboard(self.letters_lower)
        elif key == 'BACK':
            self.key_pressed.emit('\b')
        elif key == 'ABC':
            self.symbols_mode = False
            self.shift_active = False
            self._build_keyboard(self.letters_lower)
        elif key == 'ENTER':
            self.enter_pressed.emit()
        else:
            self.key_pressed.emit(key)
            if self.shift_active and not self.symbols_mode:
                self.shift_active = False
                self._build_keyboard(self.letters_lower)


class PasswordInputPopup(QWidget):
    """Password input popup with on-screen keyboard"""
    
    password_entered = pyqtSignal(str)
    cancelled = pyqtSignal()
    
    def __init__(self, parent=None, network_name: str = ""):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.raise_()
        
        self.network_name = network_name
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Dark overlay
        self.overlay = QFrame(self)
        self.overlay.setStyleSheet("background-color: rgba(0, 0, 0, 0.8);")
        
        # Container
        self.container = QFrame(self)
        self.container.setObjectName("passwordContainer")
        self.container.setStyleSheet("""
            QFrame#passwordContainer {
                background-color: #1a1a1a;
                border-radius: 16px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            QLabel {
                color: #ffffff;
                background: transparent;
            }
            QLabel#title {
                font-size: 16px;
                font-weight: 600;
            }
            QLabel#networkName {
                font-size: 14px;
                color: #4a9eff;
            }
            QLineEdit {
                background-color: #2a2a2a;
                border: 1px solid #444444;
                border-radius: 8px;
                padding: 12px 14px;
                color: #ffffff;
                font-size: 16px;
            }
            QLineEdit:focus {
                border-color: #4a9eff;
            }
            QPushButton#cancelBtn {
                background-color: #333333;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
                color: #ffffff;
                font-size: 14px;
                font-weight: 500;
            }
            QPushButton#cancelBtn:pressed {
                background-color: #444444;
            }
            QPushButton#connectBtn {
                background-color: #2563eb;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
                color: #ffffff;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton#connectBtn:pressed {
                background-color: #3b82f6;
            }
        """)
        
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        
        # Header
        header = QHBoxLayout()
        title = QLabel("Enter Password")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        
        close_btn = QPushButton()
        close_btn.setIcon(_load_svg_icon("close", 20, "#888888"))
        close_btn.setIconSize(QSize(20, 20))
        close_btn.setFixedSize(32, 32)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
            }
            QPushButton:pressed {
                background-color: #333333;
                border-radius: 16px;
            }
        """)
        close_btn.clicked.connect(self._on_cancel)
        header.addWidget(close_btn)
        layout.addLayout(header)
        
        # Network name
        network_label = QLabel(network_name)
        network_label.setObjectName("networkName")
        layout.addWidget(network_label)
        
        # Password input with visibility toggle
        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)
        
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        input_layout.addWidget(self.password_input)
        
        self.show_btn = QPushButton()
        self.show_btn.setIcon(_load_svg_icon("visibility", 20, "#888888"))
        self.show_btn.setIconSize(QSize(20, 20))
        self.show_btn.setFixedSize(44, 44)
        self.show_btn.setCheckable(True)
        self.show_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                border: 1px solid #444444;
                border-radius: 8px;
            }
            QPushButton:checked {
                background-color: #3a3a3a;
            }
        """)
        self.show_btn.clicked.connect(self._toggle_visibility)
        input_layout.addWidget(self.show_btn)
        
        layout.addLayout(input_layout)
        
        # Keyboard
        self.keyboard = OnScreenKeyboard()
        self.keyboard.key_pressed.connect(self._on_key)
        self.keyboard.enter_pressed.connect(self._on_connect)
        layout.addWidget(self.keyboard)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(cancel_btn)
        
        connect_btn = QPushButton("Connect")
        connect_btn.setObjectName("connectBtn")
        connect_btn.clicked.connect(self._on_connect)
        btn_layout.addWidget(connect_btn)
        
        layout.addLayout(btn_layout)
        
        self.container.setFixedWidth(480)
        
        # Animation
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.fade_animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_animation.setDuration(150)
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
    
    def showEvent(self, event):
        super().showEvent(event)
        if self.parent():
            parent_rect = self.parent().rect()
            self.overlay.setGeometry(parent_rect)
            self.container.adjustSize()
            x = (parent_rect.width() - self.container.width()) // 2
            y = (parent_rect.height() - self.container.height()) // 2
            self.container.move(x, y)
            self.setGeometry(parent_rect)
            self.fade_animation.start()
            self.password_input.setFocus()
    
    def _on_key(self, key):
        if key == '\b':
            self.password_input.setText(self.password_input.text()[:-1])
        else:
            self.password_input.setText(self.password_input.text() + key)
    
    def _toggle_visibility(self):
        if self.show_btn.isChecked():
            self.password_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_btn.setIcon(_load_svg_icon("visibility_off", 20, "#888888"))
        else:
            self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_btn.setIcon(_load_svg_icon("visibility", 20, "#888888"))
    
    def _on_connect(self):
        password = self.password_input.text()
        if password:
            self.password_entered.emit(password)
            self._close()
    
    def _on_cancel(self):
        self.cancelled.emit()
        self._close()
    
    def _close(self):
        fade_out = QPropertyAnimation(self.opacity_effect, b"opacity")
        fade_out.setDuration(100)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.finished.connect(self.close)
        self._fade_out = fade_out
        fade_out.start()


class TextInputPopup(QWidget):
    """Universal text input popup with on-screen keyboard"""
    
    text_entered = pyqtSignal(str)
    cancelled = pyqtSignal()
    
    def __init__(self, parent=None, title: str = "Enter Text", initial_text: str = "", placeholder: str = ""):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.raise_()
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Dark overlay
        self.overlay = QFrame(self)
        self.overlay.setStyleSheet("background-color: rgba(0, 0, 0, 0.8);")
        
        # Container
        self.container = QFrame(self)
        self.container.setObjectName("textInputContainer")
        self.container.setStyleSheet("""
            QFrame#textInputContainer {
                background-color: #1a1a1a;
                border-radius: 16px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            QLabel {
                color: #ffffff;
                background: transparent;
            }
            QLabel#title {
                font-size: 16px;
                font-weight: 600;
            }
            QLineEdit {
                background-color: #2a2a2a;
                border: 1px solid #444444;
                border-radius: 8px;
                padding: 12px 14px;
                color: #ffffff;
                font-size: 16px;
            }
            QLineEdit:focus {
                border-color: #4a9eff;
            }
            QPushButton#cancelBtn {
                background-color: #333333;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
                color: #ffffff;
                font-size: 14px;
                font-weight: 500;
            }
            QPushButton#cancelBtn:pressed {
                background-color: #444444;
            }
            QPushButton#okBtn {
                background-color: #2563eb;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
                color: #ffffff;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton#okBtn:pressed {
                background-color: #3b82f6;
            }
        """)
        
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        
        # Header
        header = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("title")
        header.addWidget(title_label)
        header.addStretch()
        
        close_btn = QPushButton()
        close_btn.setIcon(_load_svg_icon("close", 20, "#888888"))
        close_btn.setIconSize(QSize(20, 20))
        close_btn.setFixedSize(32, 32)
        close_btn.setStyleSheet("""
            QPushButton { background-color: transparent; border: none; }
            QPushButton:pressed { background-color: #333333; border-radius: 16px; }
        """)
        close_btn.clicked.connect(self._on_cancel)
        header.addWidget(close_btn)
        layout.addLayout(header)
        
        # Text input
        self.text_input = QLineEdit()
        self.text_input.setText(initial_text)
        self.text_input.setPlaceholderText(placeholder)
        layout.addWidget(self.text_input)
        
        # Keyboard
        self.keyboard = OnScreenKeyboard()
        self.keyboard.key_pressed.connect(self._on_key)
        self.keyboard.enter_pressed.connect(self._on_ok)
        layout.addWidget(self.keyboard)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("okBtn")
        ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(ok_btn)
        
        layout.addLayout(btn_layout)
        
        self.container.setFixedWidth(480)
        
        # Animation
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.fade_animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_animation.setDuration(150)
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
    
    def showEvent(self, event):
        super().showEvent(event)
        if self.parent():
            parent_rect = self.parent().rect()
            self.overlay.setGeometry(parent_rect)
            self.container.adjustSize()
            x = (parent_rect.width() - self.container.width()) // 2
            y = (parent_rect.height() - self.container.height()) // 2
            self.container.move(x, y)
            self.setGeometry(parent_rect)
            self.fade_animation.start()
    
    def _on_key(self, key):
        if key == '\b':
            self.text_input.setText(self.text_input.text()[:-1])
        else:
            self.text_input.setText(self.text_input.text() + key)
    
    def _on_ok(self):
        self.text_entered.emit(self.text_input.text())
        self._close()
    
    def _on_cancel(self):
        self.cancelled.emit()
        self._close()
    
    def _close(self):
        fade_out = QPropertyAnimation(self.opacity_effect, b"opacity")
        fade_out.setDuration(100)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.finished.connect(self.close)
        self._fade_out = fade_out
        fade_out.start()


class WiFiPopup(QWidget):
    """WiFi network selection popup"""
    
    closed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.raise_()
        
        self.scan_thread = None
        self.connect_thread = None
        self.selected_network = None
        self.password_popup = None
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Dark overlay
        self.overlay = QFrame(self)
        self.overlay.setStyleSheet("background-color: rgba(0, 0, 0, 0.7);")
        
        # Container
        self.container = QFrame(self)
        self.container.setObjectName("wifiContainer")
        self.container.setStyleSheet("""
            QFrame#wifiContainer {
                background-color: #1a1a1a;
                border-radius: 16px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            QLabel {
                color: #ffffff;
                background: transparent;
            }
            QLabel#title {
                font-size: 18px;
                font-weight: 600;
                color: #ffffff;
            }
            QLabel#subtitle {
                font-size: 12px;
                color: #888888;
            }
            QLineEdit {
                background-color: #2a2a2a;
                border: 1px solid #444444;
                border-radius: 8px;
                padding: 10px 14px;
                color: #ffffff;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #4a9eff;
            }
            QPushButton {
                background-color: #333333;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                color: #ffffff;
                font-size: 14px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #444444;
            }
            QPushButton#connectBtn {
                background-color: #2563eb;
            }
            QPushButton#connectBtn:hover {
                background-color: #3b82f6;
            }
            QPushButton#connectBtn:disabled {
                background-color: #1e3a5f;
                color: #666666;
            }
            QListWidget {
                background-color: #222222;
                border: 1px solid #333333;
                border-radius: 8px;
                padding: 4px;
                outline: none;
            }
            QListWidget::item {
                background-color: transparent;
                border-radius: 6px;
                padding: 10px 12px;
                margin: 2px 0;
                color: #ffffff;
            }
            QListWidget::item:selected {
                background-color: #2563eb;
            }
            QListWidget::item:hover:!selected {
                background-color: #333333;
            }
        """)
        
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        
        # Header
        header = QHBoxLayout()
        
        wifi_icon = QLabel()
        wifi_pixmap = QPixmap(24, 24)
        wifi_pixmap.fill(Qt.GlobalColor.transparent)
        wifi_renderer = QSvgRenderer(_get_icon_path("wifi"))
        wifi_painter = QPainter(wifi_pixmap)
        wifi_renderer.render(wifi_painter)
        wifi_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        wifi_painter.fillRect(wifi_pixmap.rect(), QColor("#4a9eff"))
        wifi_painter.end()
        wifi_icon.setPixmap(wifi_pixmap)
        header.addWidget(wifi_icon)
        
        title = QLabel("WiFi Networks")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        
        self.refresh_btn = QPushButton()
        self.refresh_btn.setIcon(_load_svg_icon("refresh", 20, "#ffffff"))
        self.refresh_btn.setIconSize(QSize(20, 20))
        self.refresh_btn.setFixedSize(36, 36)
        self.refresh_btn.clicked.connect(self.scan_networks)
        header.addWidget(self.refresh_btn)
        
        close_btn = QPushButton()
        close_btn.setIcon(_load_svg_icon("close", 20, "#ffffff"))
        close_btn.setIconSize(QSize(20, 20))
        close_btn.setFixedSize(36, 36)
        close_btn.clicked.connect(self.close_popup)
        header.addWidget(close_btn)
        
        layout.addLayout(header)
        
        # Status label
        self.status_label = QLabel("Scanning...")
        self.status_label.setObjectName("subtitle")
        layout.addWidget(self.status_label)
        
        # Network list
        self.network_list = QListWidget()
        self.network_list.setMinimumHeight(220)
        self.network_list.itemClicked.connect(self.on_network_selected)
        self.network_list.itemDoubleClicked.connect(self.on_network_double_clicked)
        layout.addWidget(self.network_list)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.close_popup)
        button_layout.addWidget(self.cancel_btn)
        
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("connectBtn")
        self.connect_btn.setEnabled(False)
        self.connect_btn.clicked.connect(self.connect_to_network)
        button_layout.addWidget(self.connect_btn)
        
        layout.addLayout(button_layout)
        
        self.container.setFixedWidth(520)
        
        # Fade animation
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.fade_animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_animation.setDuration(200)
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
        
    def showEvent(self, event):
        super().showEvent(event)
        if self.parent():
            parent_rect = self.parent().rect()
            self.overlay.setGeometry(parent_rect)
            
            self.container.adjustSize()
            x = (parent_rect.width() - self.container.width()) // 2
            y = (parent_rect.height() - self.container.height()) // 2
            self.container.move(x, y)
            
            self.setGeometry(parent_rect)
            self.fade_animation.start()
            
            # Start scanning
            QTimer.singleShot(100, self.scan_networks)
    
    def scan_networks(self):
        """Scan for WiFi networks"""
        self.status_label.setText("Scanning...")
        self.network_list.clear()
        self.refresh_btn.setEnabled(False)
        
        self.scan_thread = WiFiScanThread()
        self.scan_thread.networks_found.connect(self.on_networks_found)
        self.scan_thread.error_occurred.connect(self.on_scan_error)
        self.scan_thread.finished.connect(lambda: self.refresh_btn.setEnabled(True))
        self.scan_thread.start()
    
    def _get_signal_icon(self, signal: int) -> QIcon:
        """Get signal strength icon"""
        if signal >= 70:
            return _load_svg_icon("signal_4", 18, "#4ade80")
        elif signal >= 50:
            return _load_svg_icon("signal_3", 18, "#a3e635")
        elif signal >= 30:
            return _load_svg_icon("signal_2", 18, "#facc15")
        else:
            return _load_svg_icon("signal_1", 18, "#f87171")
    
    @pyqtSlot(list)
    def on_networks_found(self, networks):
        """Handle found networks"""
        self.network_list.clear()
        self.network_list.setIconSize(QSize(18, 18))
        
        if not networks:
            self.status_label.setText("No networks found")
            return
        
        self.status_label.setText(f"Found {len(networks)} networks")
        
        for net in networks:
            signal = net['signal']
            
            # Build display text
            prefix = "✓ " if net['connected'] else "   "
            suffix = " 🔒" if net['security'] else ""
            text = f"{prefix}{net['ssid']}{suffix}"
            
            item = QListWidgetItem(text)
            item.setIcon(self._get_signal_icon(signal))
            item.setData(Qt.ItemDataRole.UserRole, net)
            self.network_list.addItem(item)
    
    @pyqtSlot(str)
    def on_scan_error(self, error):
        """Handle scan error"""
        self.status_label.setText(f"Error: {error}")
    
    def on_network_selected(self, item):
        """Handle network selection"""
        self.selected_network = item.data(Qt.ItemDataRole.UserRole)
        self.connect_btn.setEnabled(True)
    
    def on_network_double_clicked(self, item):
        """Handle double click - connect immediately"""
        self.on_network_selected(item)
        self.connect_to_network()
    
    def connect_to_network(self):
        """Connect to selected network"""
        if not self.selected_network:
            return
        
        if self.selected_network['security']:
            self._show_password_popup()
        else:
            self._do_connect(self.selected_network['ssid'], "")
    
    def _show_password_popup(self):
        """Show password input popup"""
        if self.password_popup:
            self.password_popup.close()
        
        self.password_popup = PasswordInputPopup(self.parent(), self.selected_network['ssid'])
        self.password_popup.password_entered.connect(self._on_password_entered)
        self.password_popup.cancelled.connect(self._on_password_cancelled)
        self.password_popup.show()
    
    def _on_password_entered(self, password):
        """Handle password entered from popup"""
        self.password_popup = None
        self._do_connect(self.selected_network['ssid'], password)
    
    def _on_password_cancelled(self):
        """Handle password popup cancelled"""
        self.password_popup = None
    
    def _do_connect(self, ssid: str, password: str):
        """Actually connect to network"""
        self.status_label.setText(f"Connecting to {ssid}...")
        self.connect_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        
        self.connect_thread = WiFiConnectThread(ssid, password)
        self.connect_thread.connection_result.connect(self.on_connection_result)
        self.connect_thread.start()
    
    @pyqtSlot(bool, str)
    def on_connection_result(self, success, message):
        """Handle connection result"""
        self.connect_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        
        if success:
            self.status_label.setText(message)
            # Close after success
            QTimer.singleShot(1500, self.close_popup)
        else:
            self.status_label.setText(f"Failed: {message}")
    
    def close_popup(self):
        """Close the popup"""
        fade_out = QPropertyAnimation(self.opacity_effect, b"opacity")
        fade_out.setDuration(150)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.finished.connect(self._finish_close)
        self._fade_out = fade_out
        fade_out.start()
    
    def _finish_close(self):
        self.closed.emit()
        self.close()
