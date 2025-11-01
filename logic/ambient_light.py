"""Ambient light detection using a webcam for automatic brightness control."""

from __future__ import annotations

import os
import platform
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
        self._is_raspberry_pi = self._detect_raspberry_pi()
    
    @staticmethod
    def _detect_raspberry_pi() -> bool:
        """Определяет, работает ли код на Raspberry Pi"""
        try:
            with open('/proc/cpuinfo', 'r') as f:
                cpuinfo = f.read()
                return 'Raspberry Pi' in cpuinfo or 'BCM' in cpuinfo
        except:
            return False

    def run(self) -> None:
        print("[AutoBrightness] Starting ambient light monitor thread", file=sys.stderr, flush=True)
        if cv2 is None or np is None:
            print("[AutoBrightness] ERROR: OpenCV or NumPy not available", file=sys.stderr, flush=True)
            self.errorOccurred.emit("missing_backend")
            return

        # Определяем бэкенд в зависимости от платформы
        if os.name == "nt":
            backends = [cv2.CAP_DSHOW]
        elif self._is_raspberry_pi:
            print("[AutoBrightness] Raspberry Pi detected", file=sys.stderr, flush=True)
            # Для Raspberry Pi пробуем V4L2 и GSTREAMER
            backends = [cv2.CAP_V4L2, cv2.CAP_GSTREAMER, cv2.CAP_ANY]
        else:
            backends = [cv2.CAP_V4L2, cv2.CAP_ANY]
        
        # Пробуем открыть камеру с разными бэкендами
        self._capture = None
        for backend in backends:
            backend_name = self._get_backend_name(backend)
            print(f"[AutoBrightness] Trying backend: {backend_name} (index: {self._camera_index})", file=sys.stderr, flush=True)
            self._capture = self._open_camera(backend)
            if self._capture:
                print(f"[AutoBrightness] Camera opened successfully with {backend_name}", file=sys.stderr, flush=True)
                break
        
        if not self._capture:
            print("[AutoBrightness] ERROR: Failed to open camera with any backend", file=sys.stderr, flush=True)
            self.errorOccurred.emit("camera_unavailable")
            return

        # Lower resolution is enough for a mean brightness estimate
        # На Raspberry Pi некоторые настройки могут не работать
        if not self._is_raspberry_pi:
            self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
            self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        else:
            # Для RPi используем значения по умолчанию или меньшие
            print("[AutoBrightness] Using default camera resolution for Raspberry Pi", file=sys.stderr, flush=True)
        
        self._running = True
        failed_reads = 0
        print("[AutoBrightness] Camera opened successfully, starting capture loop", file=sys.stderr, flush=True)

        while self._running:
            ret, frame = self._capture.read()
            if not ret or frame is None:
                failed_reads += 1
                print(f"[AutoBrightness] Failed to read frame (attempt {failed_reads}/5)", file=sys.stderr, flush=True)
                if failed_reads >= 5:
                    print("[AutoBrightness] ERROR: Too many failed reads, stopping", file=sys.stderr, flush=True)
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

    @staticmethod
    def _get_backend_name(backend: int) -> str:
        """Возвращает название бэкенда для логирования"""
        backend_names = {
            cv2.CAP_V4L2: "V4L2",
            cv2.CAP_GSTREAMER: "GStreamer",
            cv2.CAP_DSHOW: "DirectShow",
            cv2.CAP_ANY: "ANY",
        }
        return backend_names.get(backend, f"Unknown({backend})")
    
    def _open_camera(self, backend: int):
        """Try to open the preferred camera, falling back to nearby indices."""
        probe_indices = self._build_probe_indices()
        print(f"[AutoBrightness] Probing camera indices: {probe_indices}", file=sys.stderr, flush=True)
        for idx in probe_indices:
            print(f"[AutoBrightness] Trying camera index {idx}...", file=sys.stderr, flush=True)
            try:
                capture = cv2.VideoCapture(idx, backend)
                if capture and capture.isOpened():
                    # Для Raspberry Pi попробуем прочитать тестовый кадр
                    if self._is_raspberry_pi:
                        ret, test_frame = capture.read()
                        if not ret or test_frame is None:
                            print(f"[AutoBrightness] Camera {idx} opened but cannot read frames", file=sys.stderr, flush=True)
                            capture.release()
                            continue
                        print(f"[AutoBrightness] Camera {idx} test read successful", file=sys.stderr, flush=True)
                    
                    print(f"[AutoBrightness] Camera {idx} opened successfully", file=sys.stderr, flush=True)
                    if idx != self._camera_index:
                        self._camera_index = idx
                        print(f"[AutoBrightness] Camera index resolved to {idx}", file=sys.stderr, flush=True)
                        self.cameraIndexResolved.emit(idx)
                    return capture
                if capture:
                    capture.release()
                print(f"[AutoBrightness] Camera {idx} failed to open", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[AutoBrightness] Exception opening camera {idx}: {e}", file=sys.stderr, flush=True)
        print("[AutoBrightness] No cameras available", file=sys.stderr, flush=True)
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
