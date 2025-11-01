"""User interface components."""

from .animations import AnimatedPanel, AnimatedSlideContainer, SlideType
from .controls import ModernColorButton, ModernSlider
from .ndot_clock_slider import NDotClockSlider
from .popups import ConfirmationPopup, DownloadProgressPopup, NotificationPopup

__all__ = [
    "AnimatedPanel",
    "AnimatedSlideContainer",
    "SlideType",
    "ModernColorButton",
    "ModernSlider",
    "NDotClockSlider",
    "ConfirmationPopup",
    "DownloadProgressPopup",
    "NotificationPopup",
]
