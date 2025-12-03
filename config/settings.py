"""Application settings dataclasses with validation."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


class Language(str, Enum):
    """Supported languages."""
    ENGLISH = "EN"
    RUSSIAN = "RU"
    UKRAINIAN = "UA"


@dataclass
class ColorRGB:
    """RGB color representation with validation."""
    r: int
    g: int
    b: int
    
    def __post_init__(self):
        """Validate RGB values."""
        for component, value in [('r', self.r), ('g', self.g), ('b', self.b)]:
            if not 0 <= value <= 255:
                raise ValueError(f"Color {component} must be 0-255, got {value}")
    
    def to_tuple(self) -> Tuple[int, int, int]:
        """Convert to tuple format."""
        return (self.r, self.g, self.b)
    
    @classmethod
    def from_tuple(cls, rgb: Tuple[int, int, int]) -> 'ColorRGB':
        """Create from tuple."""
        return cls(r=rgb[0], g=rgb[1], b=rgb[2])
    
    def to_qcolor(self):
        """Convert to QColor (import done at call time to avoid circular deps)."""
        from PyQt6.QtGui import QColor
        return QColor(self.r, self.g, self.b)


@dataclass
class Location:
    """Geographic location."""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    
    def is_valid(self) -> bool:
        """Check if location has valid coordinates."""
        return (
            self.latitude is not None 
            and self.longitude is not None
            and -90 <= self.latitude <= 90
            and -180 <= self.longitude <= 180
        )
    
    def to_dict(self) -> Dict[str, Optional[float]]:
        """Convert to dictionary format."""
        return {'lat': self.latitude, 'lon': self.longitude}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Optional[float]]) -> 'Location':
        """Create from dictionary."""
        return cls(latitude=data.get('lat'), longitude=data.get('lon'))


@dataclass
class AutoBrightnessSettings:
    """Auto-brightness configuration."""
    enabled: bool = False
    camera_index: int = 0
    interval_ms: int = 1000
    min_brightness: float = 0.0
    max_brightness: float = 1.0
    smoothing_buffer_size: int = 3
    
    def __post_init__(self):
        """Validate settings."""
        if not 0.0 <= self.min_brightness <= 1.0:
            raise ValueError(f"min_brightness must be 0.0-1.0, got {self.min_brightness}")
        if not 0.0 <= self.max_brightness <= 1.0:
            raise ValueError(f"max_brightness must be 0.0-1.0, got {self.max_brightness}")
        if self.min_brightness >= self.max_brightness:
            raise ValueError("min_brightness must be less than max_brightness")
        if self.interval_ms < 100:
            raise ValueError(f"interval_ms must be >= 100, got {self.interval_ms}")
        if self.smoothing_buffer_size < 1:
            raise ValueError(f"smoothing_buffer_size must be >= 1, got {self.smoothing_buffer_size}")


@dataclass
class SlideConfig:
    """Configuration for a single slide."""
    type: str  # 'clock', 'weather', 'custom', 'youtube', 'home_assistant'
    enabled: bool = True
    settings: Dict = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate slide type."""
        valid_types = {'clock', 'weather', 'custom', 'youtube', 'home_assistant'}
        if self.type not in valid_types:
            raise ValueError(f"Invalid slide type: {self.type}. Must be one of {valid_types}")


@dataclass
class ClockSettings:
    """Main application settings."""
    
    # Display settings
    user_brightness: float = 0.8
    digit_color: ColorRGB = field(default_factory=lambda: ColorRGB(246, 246, 255))
    background_color: ColorRGB = field(default_factory=lambda: ColorRGB(0, 0, 0))
    colon_color: ColorRGB = field(default_factory=lambda: ColorRGB(220, 40, 40))
    
    # Localization
    language: Language = Language.RUSSIAN
    
    # Slides
    slides: List[SlideConfig] = field(default_factory=list)
    
    # Location
    location: Location = field(default_factory=Location)
    
    # Auto-brightness
    auto_brightness: AutoBrightnessSettings = field(default_factory=AutoBrightnessSettings)
    
    def __post_init__(self):
        """Validate settings."""
        if not 0.0 <= self.user_brightness <= 1.0:
            raise ValueError(f"user_brightness must be 0.0-1.0, got {self.user_brightness}")
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'user_brightness': self.user_brightness,
            'digit_color': self.digit_color.to_tuple(),
            'background_color': self.background_color.to_tuple(),
            'colon_color': self.colon_color.to_tuple(),
            'language': self.language.value,
            'slides': [
                {'type': s.type, 'enabled': s.enabled, 'settings': s.settings}
                for s in self.slides
            ],
            'location': self.location.to_dict(),
            'auto_brightness_enabled': self.auto_brightness.enabled,
            'auto_brightness_camera': self.auto_brightness.camera_index,
            'auto_brightness_interval_ms': self.auto_brightness.interval_ms,
            'auto_brightness_min': self.auto_brightness.min_brightness,
            'auto_brightness_max': self.auto_brightness.max_brightness,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ClockSettings':
        """Create from dictionary loaded from JSON."""
        return cls(
            user_brightness=data.get('user_brightness', 0.8),
            digit_color=ColorRGB.from_tuple(data.get('digit_color', (246, 246, 255))),
            background_color=ColorRGB.from_tuple(data.get('background_color', (0, 0, 0))),
            colon_color=ColorRGB.from_tuple(data.get('colon_color', (220, 40, 40))),
            language=Language(data.get('language', 'RU')),
            slides=[
                SlideConfig(
                    type=s.get('type', 'clock'),
                    enabled=s.get('enabled', True),
                    settings=s.get('settings', {})
                )
                for s in data.get('slides', [])
            ],
            location=Location.from_dict(data.get('location', {})),
            auto_brightness=AutoBrightnessSettings(
                enabled=data.get('auto_brightness_enabled', False),
                camera_index=data.get('auto_brightness_camera', 0),
                interval_ms=data.get('auto_brightness_interval_ms', 1000),
                min_brightness=data.get('auto_brightness_min', 0.0),
                max_brightness=data.get('auto_brightness_max', 1.0),
            ),
        )
