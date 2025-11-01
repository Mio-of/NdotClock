"""Helpers for controlling system backlight brightness."""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass
class BacklightInfo:
    """Information about a detected backlight device."""

    name: str
    brightness_path: str
    max_brightness: int

    @property
    def directory(self) -> str:
        return os.path.dirname(self.brightness_path)


class SystemBacklightController:
    """Control screen backlight by writing to /sys/class/backlight."""

    def __init__(self, info: BacklightInfo) -> None:
        self._info = info
        self._last_raw_value: Optional[int] = None

    @property
    def name(self) -> str:
        return self._info.name

    @property
    def max_brightness(self) -> int:
        return self._info.max_brightness

    @classmethod
    def auto_detect(cls) -> Optional["SystemBacklightController"]:
        """Try to find a writable backlight device."""
        for info in cls._enumerate_backlights():
            try:
                controller = cls(info)
                controller.get_level()  # Validate readability
                return controller
            except Exception:
                continue
        return None

    @classmethod
    def from_directory(cls, directory: str) -> Optional["SystemBacklightController"]:
        """Create controller from explicit backlight directory."""
        brightness_path = os.path.join(directory, "brightness")
        max_path = os.path.join(directory, "max_brightness")
        if not (os.path.exists(brightness_path) and os.path.exists(max_path)):
            return None
        try:
            max_value = cls._read_int(max_path)
        except Exception:
            return None
        info = BacklightInfo(
            name=os.path.basename(directory.rstrip("/")),
            brightness_path=brightness_path,
            max_brightness=max_value,
        )
        return cls(info)

    @classmethod
    def _enumerate_backlights(cls) -> Iterable[BacklightInfo]:
        """Yield information about discovered backlight devices."""
        candidates = sorted(glob.glob("/sys/class/backlight/*"))
        # Prefer Raspberry Pi specific backlight names first
        preferred_prefixes = ("rpi_backlight", "panel", "DSI")
        candidates = sorted(
            candidates,
            key=lambda path: (
                0
                if os.path.basename(path).startswith(preferred_prefixes)
                else 1,
                path,
            ),
        )
        for directory in candidates:
            brightness_path = os.path.join(directory, "brightness")
            max_path = os.path.join(directory, "max_brightness")
            if not (os.path.exists(brightness_path) and os.path.exists(max_path)):
                continue
            try:
                max_value = cls._read_int(max_path)
            except Exception:
                continue
            yield BacklightInfo(
                name=os.path.basename(directory.rstrip("/")),
                brightness_path=brightness_path,
                max_brightness=max_value,
            )

    def set_level(self, level: float) -> None:
        """Set backlight level, clamping to 0..1."""
        clamped = max(0.0, min(1.0, float(level)))
        raw_value = int(round(clamped * self._info.max_brightness))
        if self._last_raw_value is not None and raw_value == self._last_raw_value:
            return

        try:
            with open(self._info.brightness_path, "w", encoding="utf-8") as handle:
                handle.write(f"{raw_value}\n")
        except PermissionError as exc:
            raise PermissionError(
                f"Permission denied while writing {self._info.brightness_path}. "
                "Grant write access or run the app with sudo/setcap."
            ) from exc
        self._last_raw_value = raw_value

    def get_level(self) -> float:
        """Return current backlight level in range 0..1."""
        raw_value = self._read_int(self._info.brightness_path)
        self._last_raw_value = raw_value
        if self._info.max_brightness <= 0:
            return 0.0
        return max(0.0, min(1.0, raw_value / self._info.max_brightness))

    @staticmethod
    def _read_int(path: str) -> int:
        with open(path, "r", encoding="utf-8") as handle:
            return int(handle.read().strip())
