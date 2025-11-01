"""Ambient light detection using a webcam for automatic brightness control."""

from __future__ import annotations

import os
import sys
from typing import List, Optional, Tuple

from PyQt6.QtCore import QThread, pyqtSignal

try:
    import numpy as np
except ImportError:  # pragma: no cover - handled at runtime
    np = None  # type: ignore

try:
    import cv2
except ImportError:  # pragma: no cover - handled at runtime
    cv2 = None  # type: ignore

_PICAMERA2_IMPORT_ERROR: Optional[BaseException] = None
_PICAMERA2_CLASS = None


def _ensure_picamera2():
    """Attempt to import Picamera2 lazily with graceful failure handling."""
    global _PICAMERA2_CLASS, _PICAMERA2_IMPORT_ERROR
    if _PICAMERA2_CLASS is not None:
        return _PICAMERA2_CLASS
    if _PICAMERA2_IMPORT_ERROR is not None:
        return None

    try:
        from picamera2 import Picamera2 as _Picamera2  # type: ignore

        _PICAMERA2_CLASS = _Picamera2
        _PICAMERA2_IMPORT_ERROR = None
        return _PICAMERA2_CLASS
    except Exception as exc:  # pragma: no cover - optional dependency on Raspberry Pi
        _PICAMERA2_IMPORT_ERROR = exc
        return None


class _Picamera2Adapter:
    """Minimal adapter to provide a cv2-like interface for Picamera2."""

    def __init__(self, resolution: Tuple[int, int] = (640, 480)) -> None:
        picam_class = _ensure_picamera2()
        if picam_class is None:
            raise RuntimeError("Picamera2 not available")

        self._picam = picam_class()
        # Prefer a lightweight preview configuration for quick luminance sampling
        config = self._picam.create_preview_configuration(
            main={"size": resolution, "format": "RGB888"}
        )
        self._picam.configure(config)
        self._picam.start()
        self._closed = False

    def isOpened(self) -> bool:
        """Mirror cv2.VideoCapture interface."""
        return not self._closed

    def read(self):
        """Return a frame compatible with the ambient light monitor loop."""
        if self._closed:
            return False, None
        try:
            frame = self._picam.capture_array()
            return True, frame
        except Exception:
            return False, None

    def release(self) -> None:
        """Stop camera stream and release hardware resources."""
        if self._closed:
            return
        try:
            self._picam.stop()
        except Exception:
            pass
        try:
            self._picam.close()
        except Exception:
            pass
        self._closed = True


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
        self._using_picamera2 = False
        self._is_raspberry_pi = self._detect_raspberry_pi()
        self._enable_picamera2 = (
            os.environ.get("NDOT_AUTO_BRIGHTNESS_ENABLE_PICAMERA2", "").lower()
            in ("1", "true", "yes")
        )
        # Allow overriding the camera source via environment variable.
        # Useful for forcing a specific index, device path or GStreamer pipeline.
        env_override = os.environ.get("NDOT_AUTO_BRIGHTNESS_CAMERA", "").strip()
        self._camera_override = env_override or None
        # Enable verbose logging for debugging camera issues
        self._verbose = os.environ.get("NDOT_AUTO_BRIGHTNESS_VERBOSE", "").lower() in ("1", "true", "yes")
    
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
        if self._verbose:
            print("[AutoBrightness] Starting ambient light monitor thread", file=sys.stderr, flush=True)
        if np is None:
            print("[AutoBrightness] ERROR: NumPy not available", file=sys.stderr, flush=True)
            self.errorOccurred.emit("missing_backend")
            return

        if cv2 is None:
            if not self._enable_picamera2:
                print("[AutoBrightness] ERROR: OpenCV not available and Picamera2 fallback disabled", file=sys.stderr, flush=True)
                self.errorOccurred.emit("missing_backend")
                return
            if _ensure_picamera2() is None:
                print("[AutoBrightness] ERROR: Picamera2 backend not available", file=sys.stderr, flush=True)
                self.errorOccurred.emit("missing_backend")
                return

        # Honour an explicit override before attempting any automatic probing.
        self._capture = self._open_camera_override()
        if self._capture:
            self._using_picamera2 = isinstance(self._capture, _Picamera2Adapter)

        if not self._capture:
            # Определяем бэкенд в зависимости от платформы
            if os.name == "nt":
                backends = [cv2.CAP_DSHOW]
            elif self._is_raspberry_pi:
                if self._verbose:
                    print("[AutoBrightness] Raspberry Pi detected", file=sys.stderr, flush=True)
                # Для Raspberry Pi пробуем только V4L2 с индексами
                # GStreamer требует pipeline, а не индекс, поэтому пробуем его отдельно
                backends = [cv2.CAP_V4L2, cv2.CAP_ANY]
            else:
                backends = [cv2.CAP_V4L2, cv2.CAP_ANY]
            
            # Пробуем открыть камеру с разными бэкендами
            self._capture = None
            for backend in backends:
                backend_name = self._get_backend_name(backend)
                if self._verbose:
                    print(f"[AutoBrightness] Trying backend: {backend_name} (index: {self._camera_index})", file=sys.stderr, flush=True)
                self._capture = self._open_camera(backend)
                if self._capture:
                    self._using_picamera2 = False
                    print(f"[AutoBrightness] Camera opened successfully with {backend_name}", file=sys.stderr, flush=True)
                    break

        # Raspberry Pi specific fallback: attempt GStreamer pipelines (v4l2src/libcamerasrc)
        # This is the primary method for RPi 5 cameras
        if not self._capture and self._is_raspberry_pi:
            if self._verbose:
                print("[AutoBrightness] Trying Raspberry Pi GStreamer pipelines...", file=sys.stderr, flush=True)
            self._capture = self._open_raspberry_pi_camera()
            if self._capture:
                self._using_picamera2 = False

        # Final Raspberry Pi fallback: Picamera2 native capture (libcamera-based)
        if not self._capture and self._is_raspberry_pi:
            self._capture = self._open_picamera2()
            if self._capture:
                self._using_picamera2 = True
                print("[AutoBrightness] Camera opened via Picamera2 fallback", file=sys.stderr, flush=True)

        if not self._capture:
            print("[AutoBrightness] ERROR: Failed to open camera with any backend", file=sys.stderr, flush=True)
            self.errorOccurred.emit("camera_unavailable")
            return

        # Lower resolution is enough for a mean brightness estimate
        # На Raspberry Pi некоторые настройки могут не работать
        if (
            not self._is_raspberry_pi
            and not self._using_picamera2
            and cv2 is not None
            and hasattr(self._capture, "set")
        ):
            self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
            self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        elif self._verbose:
            # Для RPi используем значения по умолчанию или меньшие
            print("[AutoBrightness] Using default camera resolution for Raspberry Pi", file=sys.stderr, flush=True)
        
        self._running = True
        failed_reads = 0
        if self._verbose:
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
            if isinstance(frame, np.ndarray) and frame.ndim == 3:
                if cv2 is not None:
                    conversion = cv2.COLOR_RGB2GRAY if self._using_picamera2 else cv2.COLOR_BGR2GRAY
                    gray = cv2.cvtColor(frame, conversion)
                else:
                    gray = np.mean(frame, axis=2)
            else:
                gray = frame
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
        if self._verbose:
            print(f"[AutoBrightness] Probing camera indices: {probe_indices}", file=sys.stderr, flush=True)
        for idx in probe_indices:
            if self._verbose:
                print(f"[AutoBrightness] Trying camera index {idx}...", file=sys.stderr, flush=True)
            try:
                targets = self._build_capture_targets(idx)
                capture = None
                for target in targets:
                    if self._verbose and target != idx:
                        print(f"[AutoBrightness] -> Trying target '{target}'", file=sys.stderr, flush=True)
                    capture = cv2.VideoCapture(target, backend)
                    if capture and capture.isOpened():
                        # Для Raspberry Pi попробуем прочитать тестовый кадр
                        if self._is_raspberry_pi:
                            ret, test_frame = capture.read()
                            if not ret or test_frame is None:
                                if self._verbose:
                                    print(f"[AutoBrightness] Camera {idx} ({target}) opened but cannot read frames", file=sys.stderr, flush=True)
                                capture.release()
                                continue
                            if self._verbose:
                                print(f"[AutoBrightness] Camera {idx} ({target}) test read successful", file=sys.stderr, flush=True)

                        if self._verbose:
                            print(f"[AutoBrightness] Camera {idx} ({target}) opened successfully", file=sys.stderr, flush=True)
                        if idx != self._camera_index:
                            self._camera_index = idx
                            if self._verbose:
                                print(f"[AutoBrightness] Camera index resolved to {idx}", file=sys.stderr, flush=True)
                            self.cameraIndexResolved.emit(idx)
                        return capture
                    if capture:
                        capture.release()
                if self._verbose:
                    print(f"[AutoBrightness] Camera {idx} failed to open", file=sys.stderr, flush=True)
            except Exception as e:
                if self._verbose:
                    print(f"[AutoBrightness] Exception opening camera {idx}: {e}", file=sys.stderr, flush=True)
        if self._verbose:
            print("[AutoBrightness] No cameras available", file=sys.stderr, flush=True)
        return None

    def _open_camera_override(self):
        """Attempt to open an explicitly requested camera source."""
        if not self._camera_override:
            return None

        value = self._camera_override
        if self._verbose:
            print(f"[AutoBrightness] Using camera override: {value}", file=sys.stderr, flush=True)

        # Try interpreting override as an integer index first.
        try:
            override_index = int(value)
        except (TypeError, ValueError):
            override_index = None

        if override_index is not None:
            self._camera_index = max(0, override_index)
            if self._verbose:
                print(f"[AutoBrightness] Override parsed as camera index {self._camera_index}", file=sys.stderr, flush=True)
            return None  # fall through to normal probing with new index

        # Device path (e.g. /dev/video2)
        if value.startswith("/"):
            backend = cv2.CAP_V4L2 if hasattr(cv2, "CAP_V4L2") else cv2.CAP_ANY
            try:
                if self._verbose:
                    print(f"[AutoBrightness] Trying device path override: {value}", file=sys.stderr, flush=True)
                capture = cv2.VideoCapture(value, backend)
                if capture and capture.isOpened():
                    if self._validate_capture(capture, source=value):
                        return capture
                    capture.release()
            except Exception as exc:
                if self._verbose:
                    print(f"[AutoBrightness] Device path override failed: {exc}", file=sys.stderr, flush=True)
            return None

        # Allow forcing a raw GStreamer pipeline via override.
        # Optional gstreamer: prefix keeps backward compatibility if plain strings are used.
        pipeline_value = value
        prefix = "gstreamer:"
        if value.startswith(prefix):
            pipeline_value = value[len(prefix):].strip()
        return self._open_gstreamer_pipeline(pipeline_value, source="override")

    def _open_raspberry_pi_camera(self):
        """Probe Raspberry Pi specific backends such as libcamera pipelines."""
        pipelines = self._build_raspberry_pi_pipelines()
        if not pipelines:
            return None

        if self._verbose:
            print(f"[AutoBrightness] Trying Raspberry Pi specific pipelines: {[name for name, _ in pipelines]}", file=sys.stderr, flush=True)
        for name, pipeline in pipelines:
            capture = self._open_gstreamer_pipeline(pipeline, source=name)
            if capture:
                print(f"[AutoBrightness] Camera opened via Raspberry Pi pipeline '{name}'", file=sys.stderr, flush=True)
                return capture
        return None

    def _open_picamera2(self):
        """Fallback to Picamera2 when OpenCV backends are unavailable on Raspberry Pi."""
        if not self._enable_picamera2:
            if self._verbose:
                print("[AutoBrightness] Picamera2 fallback disabled (NDOT_AUTO_BRIGHTNESS_ENABLE_PICAMERA2 not set)", file=sys.stderr, flush=True)
            return None
        picam_class = _ensure_picamera2()
        if picam_class is None:
            if self._verbose:
                if _PICAMERA2_IMPORT_ERROR is not None:
                    print(
                        "[AutoBrightness] Picamera2 import failed, skipping fallback: "
                        f"{_PICAMERA2_IMPORT_ERROR}",
                        file=sys.stderr,
                        flush=True,
                    )
                else:
                    print("[AutoBrightness] Picamera2 module not available; skipping fallback", file=sys.stderr, flush=True)
            return None
        try:
            adapter = _Picamera2Adapter()
            return adapter
        except Exception as exc:
            if self._verbose:
                print(f"[AutoBrightness] Picamera2 fallback failed: {exc}", file=sys.stderr, flush=True)
            return None

    def _build_raspberry_pi_pipelines(self) -> List[tuple[str, str]]:
        """Return a list of candidate GStreamer pipelines for Raspberry Pi cameras."""
        pipelines: List[tuple[str, str]] = []

        # Explicit environment override has highest priority.
        env_pipeline = os.environ.get("NDOT_AUTO_BRIGHTNESS_CAMERA_PIPELINE", "").strip()
        if env_pipeline:
            pipelines.append(("env", env_pipeline))

        # Try v4l2src with common video devices (works on RPi 5 with CSI cameras)
        # Probe video0-7 as these are typically CSI camera interfaces
        for idx in range(8):
            device = f"/dev/video{idx}"
            if os.path.exists(device):
                pipelines.append(
                    (
                        f"v4l2src-{idx}",
                        f"v4l2src device={device} ! video/x-raw,width=640,height=480 "
                        f"! videoconvert ! video/x-raw,format=BGR ! appsink drop=true",
                    )
                )

        # Default libcamera pipeline suitable for modern Raspberry Pi OS images.
        pipelines.append(
            (
                "libcamerasrc-bgr",
                "libcamerasrc ! video/x-raw,width=640,height=480,framerate=30/1 "
                "! videoconvert ! video/x-raw,format=BGR ! appsink drop=true",
            )
        )
        pipelines.append(
            (
                "libcamerasrc-rgb",
                "libcamerasrc ! video/x-raw,width=640,height=480,framerate=30/1 "
                "! videoconvert ! video/x-raw,format=RGB ! appsink drop=true",
            )
        )
        # Legacy pipeline for older Raspberry Pi distributions with rpicamsrc.
        pipelines.append(
            (
                "rpicamsrc",
                "rpicamsrc ! video/x-raw,width=640,height=480,framerate=30/1 "
                "! videoconvert ! video/x-raw,format=BGR ! appsink drop=true",
            )
        )
        return pipelines

    def _open_gstreamer_pipeline(self, pipeline: str, source: str):
        """Try to open a camera using a GStreamer pipeline."""
        pipeline = pipeline.strip()
        if not pipeline:
            if self._verbose:
                print(f"[AutoBrightness] GStreamer pipeline '{source}' is empty, skipping", file=sys.stderr, flush=True)
            return None

        if not hasattr(cv2, "CAP_GSTREAMER"):
            if self._verbose:
                print(f"[AutoBrightness] OpenCV built without GStreamer support; cannot use pipeline '{source}'", file=sys.stderr, flush=True)
            return None

        if self._verbose:
            print(f"[AutoBrightness] Trying GStreamer pipeline '{source}': {pipeline}", file=sys.stderr, flush=True)
        try:
            capture = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
            if capture and capture.isOpened():
                if self._validate_capture(capture, source=source):
                    return capture
                capture.release()
            else:
                if capture:
                    capture.release()
                if self._verbose:
                    print(f"[AutoBrightness] Pipeline '{source}' failed to open", file=sys.stderr, flush=True)
        except Exception as exc:
            if self._verbose:
                print(f"[AutoBrightness] Exception while opening pipeline '{source}': {exc}", file=sys.stderr, flush=True)
        return None

    def _validate_capture(self, capture, source: str = "") -> bool:
        """Ensure that the capture can deliver frames before using it."""
        try:
            ret, test_frame = capture.read()
        except Exception as exc:  # pragma: no cover - defensive
            if self._verbose:
                print(f"[AutoBrightness] Exception while validating capture '{source}': {exc}", file=sys.stderr, flush=True)
            return False

        if not ret or test_frame is None:
            if self._verbose:
                print(f"[AutoBrightness] Capture '{source}' opened but produced no frames", file=sys.stderr, flush=True)
            return False

        if self._verbose:
            print(f"[AutoBrightness] Capture '{source}' validation succeeded", file=sys.stderr, flush=True)
        return True

    def _build_probe_indices(self) -> List[int]:
        """Return an ordered list of camera indices to probe."""
        preferred = max(0, int(self._camera_index))
        indices = [preferred]
        for idx in range(0, self.MAX_FALLBACK_CAMERAS + 1):
            if idx != preferred:
                indices.append(idx)
        return indices

    def _build_capture_targets(self, idx: int):
        """Return numeric and device path targets for a given index."""
        targets = [idx]
        device_path = f"/dev/video{idx}"
        if os.path.exists(device_path):
            targets.append(device_path)
        return targets

    @classmethod
    def dependencies_available(cls) -> bool:
        """True if the required external libraries are importable."""
        if np is None:
            return False
        if cv2 is not None:
            return True
        enable_picamera = (
            os.environ.get("NDOT_AUTO_BRIGHTNESS_ENABLE_PICAMERA2", "").lower()
            in ("1", "true", "yes")
        )
        if not enable_picamera:
            return False
        return _ensure_picamera2() is not None
