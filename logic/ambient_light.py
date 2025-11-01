"""Ambient light detection using a webcam for automatic brightness control."""

from __future__ import annotations

import os
import sys
from typing import List, Optional

from PyQt6.QtCore import QThread, pyqtSignal

try:
    import numpy as np
except ImportError:  # pragma: no cover - handled at runtime
    np = None  # type: ignore

try:
    import cv2
except ImportError:  # pragma: no cover - handled at runtime
    cv2 = None  # type: ignore


class AmbientLightMonitor(QThread):
    """Periodically samples ambient brightness from a webcam feed."""

    brightnessMeasured = pyqtSignal(float)
    errorOccurred = pyqtSignal(str)
    cameraIndexResolved = pyqtSignal(int)

    MAX_FALLBACK_CAMERAS = 3

    def __init__(
        self,
        camera_index: int = 0,
        interval_ms: int = 1500,
        parent: Optional[object] = None,
    ) -> None:
        super().__init__(parent)
        self._camera_index = camera_index
        self._interval_ms = max(250, interval_ms)
        self._running = False
        self._capture = None

    def run(self) -> None:
        if cv2 is None or np is None:
            self.errorOccurred.emit("missing_backend")
            return

        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
        self._capture = self._open_camera(backend)
        if not self._capture:
            self.errorOccurred.emit("camera_unavailable")
            return

        # Lower resolution is enough for a mean brightness estimate
        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        self._running = True
        failed_reads = 0

        while self._running:
            ret, frame = self._capture.read()
            if not ret or frame is None:
                failed_reads += 1
                if failed_reads >= 5:
                    self.errorOccurred.emit("capture_failed")
                    break
                self.msleep(self._interval_ms)
                continue

            failed_reads = 0
            gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            mean_brightness = float(np.mean(gray)) / 255.0
            clamped_brightness = max(0.0, min(1.0, mean_brightness))
            # Логируем только каждое 5-е измерение для уменьшения шума
            # print(f"[AutoBrightness] Brightness measured: {clamped_brightness:.3f}", file=sys.stderr, flush=True)
            self.brightnessMeasured.emit(clamped_brightness)
            self.msleep(self._interval_ms)

        self._release_capture()

    def stop(self) -> None:
        """Stop the sampling loop and wait for thread to finish."""
        if not self.isRunning():
            return
        self._running = False
        self.wait(1500)
        self._release_capture()

    def _release_capture(self) -> None:
        """Release webcam resource if acquired."""
        if self._capture is not None:
            try:
                self._capture.release()
            except Exception:
                pass
        self._capture = None

    def _open_camera(self, backend: int):
        """Try to open the preferred camera, falling back to nearby indices."""
        probe_indices = self._build_probe_indices()
        for idx in probe_indices:
            capture = cv2.VideoCapture(idx, backend)
            if capture and capture.isOpened():
                if idx != self._camera_index:
                    self._camera_index = idx
                    self.cameraIndexResolved.emit(idx)
                return capture
            if capture:
                capture.release()
        return None

    def _build_probe_indices(self) -> List[int]:
        """Return an ordered list of camera indices to probe."""
        preferred = max(0, int(self._camera_index))
        indices = [preferred]
        for idx in range(0, self.MAX_FALLBACK_CAMERAS + 1):
            if idx != preferred:
                indices.append(idx)
        return indices

    @classmethod
    def dependencies_available(cls) -> bool:
        """True if the required external libraries are importable."""
        return cv2 is not None and np is not None
