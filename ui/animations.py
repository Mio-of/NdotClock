"""Animated containers and panels used by the UI layer."""

from enum import Enum
from typing import Optional

from PyQt6.QtCore import pyqtProperty
from PyQt6.QtGui import QColor, QPainter, QPaintEvent
from PyQt6.QtWidgets import QFrame, QGraphicsOpacityEffect, QWidget


class SlideType(Enum):
    """Types of slides available in the application."""
    
    CLOCK = "clock"
    WEATHER = "weather"
    CUSTOM = "custom"
    WEBVIEW = "webview"
    ADD = "add"


class AnimatedSlideContainer(QWidget):
    """Container for managing slide animations with batched updates and motion blur."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._offset_x = 0.0
        self._scale = 1.0
        self._offset_y = 0.0
        self._batch_update_pending = False  # ARM optimization: batch updates

        # Fix: Motion blur effect for fast swiping (lightweight implementation)
        self._last_offset_x = 0.0
        self._velocity = 0.0
        self._motion_blur_opacity = 0.0

    def get_offset_x(self) -> float:
        return self._offset_x

    def set_offset_x(self, value: float):
        # Fix: Calculate velocity for motion blur effect
        delta = value - self._last_offset_x
        self._velocity = abs(delta)
        self._last_offset_x = value

        # Adjust motion blur opacity based on velocity (lightweight)
        # High velocity = more blur (max opacity 0.15 for subtle effect)
        if self._velocity > 50:
            self._motion_blur_opacity = min(0.15, self._velocity / 1000.0)
        else:
            self._motion_blur_opacity = 0.0

        self._offset_x = value
        self._schedule_batched_update()

    def get_scale(self) -> float:
        return self._scale

    def set_scale(self, value: float):
        self._scale = value
        self._schedule_batched_update()

    def get_offset_y(self) -> float:
        return self._offset_y

    def set_offset_y(self, value: float):
        self._offset_y = value
        self._schedule_batched_update()

    def _schedule_batched_update(self):
        """ARM optimization: batch all updates into single frame to reduce repaints."""
        if not self._batch_update_pending:
            self._batch_update_pending = True
            # Fix: Use immediate update for drag, batched for animations
            # This prevents lag during swipes while keeping optimization for animations
            from PyQt6.QtCore import QTimer
            parent = self.parentWidget()
            is_dragging = parent and hasattr(parent, 'is_dragging') and parent.is_dragging

            if is_dragging:
                # Immediate update during drag for responsive feel
                self._perform_batched_update()
            else:
                # Batched update for animations
                QTimer.singleShot(0, self._perform_batched_update)

    def _perform_batched_update(self):
        """Perform batched update of container and webviews."""
        if not self._batch_update_pending:
            return
        self._batch_update_pending = False

        # Single update call for container
        self.update()

        # Single notification to parent
        parent = self.parentWidget()
        if parent is not None:
            parent.update()

            # Update webviews once per batch instead of per property
            if hasattr(parent, 'update_active_webviews'):
                parent.update_active_webviews()

    offset_x = pyqtProperty(float, get_offset_x, set_offset_x)
    scale = pyqtProperty(float, get_scale, set_scale)
    offset_y = pyqtProperty(float, get_offset_y, set_offset_y)

    def paintEvent(self, event):
        """Add motion blur overlay during fast swipes."""
        super().paintEvent(event)

        # Only apply motion blur if velocity is high enough
        if self._motion_blur_opacity > 0.0:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)  # Fast rendering

            # Draw semi-transparent overlay for blur effect
            blur_color = QColor(0, 0, 0, int(255 * self._motion_blur_opacity))
            painter.fillRect(self.rect(), blur_color)

            painter.end()


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
