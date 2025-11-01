"""Reusable popup widgets used across the application."""

from PyQt6.QtCore import QEasingCurve, Qt, QPropertyAnimation, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


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

    def on_confirm(self):
        """Handle confirm button"""
        self.confirmed.emit()
        self.close()

    def on_cancel(self):
        """Handle cancel button"""
        self.cancelled.emit()
        self.close()
