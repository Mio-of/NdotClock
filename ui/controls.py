"""Custom controls tailored for the application styling."""

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent
from PyQt6.QtWidgets import QPushButton, QSlider


class ModernColorButton(QPushButton):
    """Color selector button with color picker dialog.
    
    Attributes:
        color_changed: Signal emitted when color is changed
    """

    color_changed = pyqtSignal(QColor)

    def __init__(self, color: QColor, button_type: str = "normal", size: int = 24) -> None:
        """Initialize color button.
        
        Args:
            color: Initial color
            button_type: Type of button ('normal' or 'background')
            size: Button size in pixels
        """
        super().__init__()
        self.current_color: QColor = color
        self.button_type: str = button_type
        self.setFixedSize(size, size)
        self.update_style()

    def mousePressEvent(self, event: Optional[QMouseEvent]) -> None:
        """Handle mouse press to show color picker.
        
        Args:
            event: Mouse event
        """
        if event and event.button() == Qt.MouseButton.LeftButton:
            from PyQt6.QtWidgets import QColorDialog
            
            options = (
                QColorDialog.ColorDialogOption.ShowAlphaChannel 
                if self.button_type != "background" 
                else QColorDialog.ColorDialogOption.DontUseNativeDialog
            )
            
            color = QColorDialog.getColor(
                self.current_color,
                self,
                "Choose Color",
                options
            )
            if color.isValid():
                self.current_color = color
                self.update_style()
                self.color_changed.emit(self.current_color)
        super().mousePressEvent(event)

    def update_style(self) -> None:
        """Update button stylesheet with current color."""
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
    """Styled horizontal slider widget with modern appearance."""

    def __init__(self, orientation: Qt.Orientation) -> None:
        """Initialize styled slider.
        
        Args:
            orientation: Slider orientation (Qt.Orientation.Horizontal or Vertical)
        """
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
