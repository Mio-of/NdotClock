import os
import sys
import math
from typing import Optional, Tuple, List
from PyQt6.QtCore import QObject, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtWidgets import QCheckBox

from logic import AmbientLightMonitor, SystemBacklightController
from ui.controls import ModernSlider

class BrightnessManager(QObject):
    """Manages screen brightness, auto-brightness, and system backlight."""
    
    brightness_changed = pyqtSignal(float)  # Emits new brightness value (0.0 - 1.0)
    auto_brightness_toggled = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, parent=None, default_settings=None):
        super().__init__(parent)
        self.default_settings = default_settings or {}
        
        # Configuration
        self._manual_brightness = self.default_settings.get('user_brightness', 0.8)
        self._auto_brightness_enabled = self.default_settings.get('auto_brightness_enabled', False)
        self._auto_brightness_min = self.default_settings.get('auto_brightness_min', 0.0)
        self._auto_brightness_max = self.default_settings.get('auto_brightness_max', 1.0)
        self._auto_brightness_camera_index = self.default_settings.get('auto_brightness_camera', 0)
        self._auto_brightness_interval_ms = self.default_settings.get('auto_brightness_interval_ms', 1000)
        
        # State
        self._auto_brightness_smoothed = self._manual_brightness
        self._current_display_brightness = self._manual_brightness
        self._cached_brightness = self._manual_brightness  # Cache for fast access
        self._ambient_light_monitor: Optional[AmbientLightMonitor] = None
        self._pending_auto_brightness_activation = False
        self._suppress_auto_brightness_save = False
        
        # Smoothing buffers
        self._ambient_brightness_buffer = []
        self._ambient_brightness_buffer_size = 5
        self._last_brightness_update_time = 0
        self._min_brightness_update_interval = 0.05
        self._last_auto_sample_time = 0.0
        self._auto_brightness_last_interval = self._auto_brightness_interval_ms / 1000.0
        
        # Logging state
        self._auto_log_last_measured: Optional[float] = None
        self._auto_log_last_target: Optional[float] = None
        self._auto_log_last_smoothed: Optional[float] = None
        
        # System backlight
        self._system_backlight: Optional[SystemBacklightController] = None
        self._system_backlight_error_notified = False
        self._system_backlight_verbose = os.environ.get("NDOT_SYSTEM_BACKLIGHT_VERBOSE", "").lower() in ("1", "true", "yes")
        self._system_backlight_last_ui_log: Optional[float] = None
        
        # Verbose logging
        auto_verbose_env = os.environ.get("NDOT_AUTO_BRIGHTNESS_VERBOSE", "")
        self._auto_brightness_verbose = auto_verbose_env.lower() in ("1", "true", "yes") or self._system_backlight_verbose
        
        # Animation
        self._brightness_animation_target = self._manual_brightness
        self._brightness_animation = QPropertyAnimation(self, b"animatedBrightness")
        self._brightness_animation.setDuration(800)
        self._brightness_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        
        # Camera reconnection state
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10
        self._reconnect_interval_ms = 30000  # 30 seconds
        self._reconnect_timer: Optional[QTimer] = None
        
        # Load environment overrides
        self._load_auto_brightness_env_overrides()
        
        # Initialize system backlight
        self._initialize_system_backlight()

    @pyqtProperty(float)
    def animatedBrightness(self):
        """Property for brightness animation"""
        return self._brightness_animation_target
    
    @animatedBrightness.setter
    def animatedBrightness(self, value: float):
        """Setter for animated brightness"""
        self._brightness_animation_target = value
        self._apply_brightness_direct(value)

    def _load_auto_brightness_env_overrides(self):
        """Load auto-brightness configuration from environment variables"""
        # Gamma curve
        gamma_env = os.environ.get("NDOT_AUTO_BRIGHTNESS_GAMMA", "").strip()
        self._auto_brightness_curve_gamma = 2.0
        if gamma_env:
            try:
                parsed_gamma = float(gamma_env)
                self._auto_brightness_curve_gamma = max(0.3, min(parsed_gamma, 5.0))
                if self._auto_brightness_verbose:
                    print(f"[AutoBrightness] NDOT_AUTO_BRIGHTNESS_GAMMA={parsed_gamma:.3f} -> using {self._auto_brightness_curve_gamma:.3f}", file=sys.stderr, flush=True)
            except ValueError:
                if self._auto_brightness_verbose:
                    print(f"[AutoBrightness] Invalid NDOT_AUTO_BRIGHTNESS_GAMMA='{gamma_env}', falling back to {self._auto_brightness_curve_gamma:.3f}", file=sys.stderr, flush=True)
        elif self._auto_brightness_verbose:
            print(f"[AutoBrightness] Using default brightness gamma {self._auto_brightness_curve_gamma:.3f}", file=sys.stderr, flush=True)

        # Interval
        interval_env = os.environ.get("NDOT_AUTO_BRIGHTNESS_INTERVAL_MS", "").strip()
        self._auto_brightness_interval_override: Optional[int] = None
        if interval_env:
            try:
                parsed_interval = int(float(interval_env))
                parsed_interval = max(150, min(parsed_interval, 60000))
                self._auto_brightness_interval_override = parsed_interval
                if self._auto_brightness_verbose:
                    print(f"[AutoBrightness] NDOT_AUTO_BRIGHTNESS_INTERVAL_MS={parsed_interval}", file=sys.stderr, flush=True)
            except ValueError:
                if self._auto_brightness_verbose:
                    print(f"[AutoBrightness] Invalid NDOT_AUTO_BRIGHTNESS_INTERVAL_MS='{interval_env}', ignoring", file=sys.stderr, flush=True)

        # Smoothing
        self._auto_brightness_smoothing = 0.85
        smoothing_env = os.environ.get("NDOT_AUTO_BRIGHTNESS_SMOOTHING", "").strip()
        if smoothing_env:
            try:
                parsed_smoothing = float(smoothing_env)
                self._auto_brightness_smoothing = max(0.0, min(parsed_smoothing, 0.95))
                if self._auto_brightness_verbose:
                    print(f"[AutoBrightness] NDOT_AUTO_BRIGHTNESS_SMOOTHING={self._auto_brightness_smoothing:.3f}", file=sys.stderr, flush=True)
            except ValueError:
                if self._auto_brightness_verbose:
                    print(f"[AutoBrightness] Invalid NDOT_AUTO_BRIGHTNESS_SMOOTHING='{smoothing_env}', ignoring", file=sys.stderr, flush=True)

        # Min interval
        min_interval_env = os.environ.get("NDOT_AUTO_BRIGHTNESS_MIN_INTERVAL", "").strip()
        if min_interval_env:
            try:
                parsed_min_interval = float(min_interval_env)
                self._min_brightness_update_interval = max(0.02, min(parsed_min_interval, 1.0))
                if self._auto_brightness_verbose:
                    print(f"[AutoBrightness] NDOT_AUTO_BRIGHTNESS_MIN_INTERVAL={self._min_brightness_update_interval:.3f}s", file=sys.stderr, flush=True)
            except ValueError:
                if self._auto_brightness_verbose:
                    print(f"[AutoBrightness] Invalid NDOT_AUTO_BRIGHTNESS_MIN_INTERVAL='{min_interval_env}', ignoring", file=sys.stderr, flush=True)

        # Min/Max overrides
        self._auto_brightness_min_override: Optional[float] = None
        self._auto_brightness_max_override: Optional[float] = None
        min_env = os.environ.get("NDOT_AUTO_BRIGHTNESS_MIN", "").strip()
        max_env = os.environ.get("NDOT_AUTO_BRIGHTNESS_MAX", "").strip()
        
        if min_env:
            try:
                parsed_min = float(min_env)
                self._auto_brightness_min_override = max(0.0, min(parsed_min, 1.0))
            except ValueError:
                if self._auto_brightness_verbose:
                    print(f"[AutoBrightness] Invalid NDOT_AUTO_BRIGHTNESS_MIN='{min_env}', ignoring", file=sys.stderr, flush=True)
        
        if max_env:
            try:
                parsed_max = float(max_env)
                self._auto_brightness_max_override = max(0.0, min(parsed_max, 1.0))
            except ValueError:
                if self._auto_brightness_verbose:
                    print(f"[AutoBrightness] Invalid NDOT_AUTO_BRIGHTNESS_MAX='{max_env}', ignoring", file=sys.stderr, flush=True)

        if (self._auto_brightness_min_override is not None and 
            self._auto_brightness_max_override is not None and 
            self._auto_brightness_min_override > self._auto_brightness_max_override):
            if self._auto_brightness_verbose:
                print("[AutoBrightness] MIN override is greater than MAX override, swapping them", file=sys.stderr, flush=True)
            self._auto_brightness_min_override, self._auto_brightness_max_override = (
                self._auto_brightness_max_override, self._auto_brightness_min_override
            )

        # Calibration decay
        calibration_decay_env = os.environ.get("NDOT_AUTO_BRIGHTNESS_CALIBRATION_DECAY", "").strip()
        self._ambient_calibration_decay = 0.005
        if calibration_decay_env:
            try:
                parsed_decay = float(calibration_decay_env)
                self._ambient_calibration_decay = max(0.001, min(parsed_decay, 0.2))
            except ValueError:
                if self._auto_brightness_verbose:
                    print(f"[AutoBrightness] Invalid NDOT_AUTO_BRIGHTNESS_CALIBRATION_DECAY='{calibration_decay_env}', ignoring", file=sys.stderr, flush=True)

        self._ambient_dynamic_min: Optional[float] = None
        self._ambient_dynamic_max: Optional[float] = None
        self._ambient_calibration_last_log: Optional[Tuple[float, float]] = None
        self._auto_brightness_has_sample = False

    def configure(self, settings: dict):
        """Update configuration from settings dictionary."""
        self._manual_brightness = float(settings.get('user_brightness', self._manual_brightness))
        self._manual_brightness = max(0.0, min(1.0, self._manual_brightness))
        
        new_enabled = bool(settings.get('auto_brightness_enabled', self._auto_brightness_enabled))
        
        self._auto_brightness_camera_index = int(settings.get('auto_brightness_camera', self._auto_brightness_camera_index))
        
        interval = settings.get('auto_brightness_interval_ms', self._auto_brightness_interval_ms)
        self._auto_brightness_interval_ms = max(250, int(interval))
        
        auto_min = float(settings.get('auto_brightness_min', self._auto_brightness_min))
        auto_max = float(settings.get('auto_brightness_max', self._auto_brightness_max))
        if auto_min > auto_max:
            auto_min, auto_max = auto_max, auto_min
        self._auto_brightness_min = max(0.0, min(1.0, auto_min))
        self._auto_brightness_max = max(self._auto_brightness_min, min(1.0, auto_max))
        
        # Re-apply env overrides if they exist
        if self._auto_brightness_interval_override is not None:
            self._auto_brightness_interval_ms = self._auto_brightness_interval_override
            
        # Apply auto brightness state
        self.set_auto_brightness_enabled(new_enabled, user_triggered=False)
            
        # Apply manual brightness immediately if auto is disabled
        if not new_enabled:
            self._apply_brightness(self._manual_brightness, from_auto=False)

    @property
    def manual_brightness(self) -> float:
        return self._manual_brightness

    def get_settings(self) -> dict:
        """Get current brightness settings."""
        return {
            'user_brightness': self._manual_brightness,
            'auto_brightness_enabled': self._auto_brightness_enabled,
            'auto_brightness_min': self._auto_brightness_min,
            'auto_brightness_max': self._auto_brightness_max,
            'auto_brightness_camera': self._auto_brightness_camera_index,
            'auto_brightness_interval_ms': self._auto_brightness_interval_ms,
        }

    def set_manual_brightness(self, value: float, *, animate: bool = True):
        """Set manual brightness."""
        self._apply_brightness(value, from_auto=False, animate=animate)

    def _initialize_system_backlight(self):
        """Configure optional system backlight controller."""
        config_value = os.environ.get("NDOT_SYSTEM_BACKLIGHT", "").strip()
        if not config_value:
            controller = SystemBacklightController.auto_detect()
            if controller:
                self._system_backlight = controller
                if self._system_backlight_verbose:
                    print(f"[Backlight] Auto-detected system backlight device '{controller.name}' (max={controller.max_brightness})", file=sys.stderr, flush=True)
                return
            else:
                if self._system_backlight_verbose:
                    print("[Backlight] No system backlight device found. Software brightness only.", file=sys.stderr, flush=True)
                return

        controller = self._resolve_backlight_controller(config_value)
        if controller is None:
            if self._system_backlight_verbose:
                print(f"[Backlight] No system backlight matched '{config_value}'. Keep using software brightness.", file=sys.stderr, flush=True)
            if not self._system_backlight_error_notified:
                self._system_backlight_error_notified = True
                self.error_occurred.emit("system_backlight_not_found")
            return

        self._system_backlight = controller
        if self._system_backlight_verbose:
            print(f"[Backlight] Using system backlight device '{controller.name}' (max={controller.max_brightness})", file=sys.stderr, flush=True)

    def _resolve_backlight_controller(self, config_value: str) -> Optional[SystemBacklightController]:
        """Resolve backlight device from configuration string."""
        parts = [part.strip() for part in config_value.split(",") if part.strip()]
        if not parts:
            parts = ["auto"]

        for part in parts:
            lowered = part.lower()
            if lowered in ("auto", "detect", "default"):
                controller = SystemBacklightController.auto_detect()
                if controller:
                    return controller
                continue

            candidate_dir = part
            if not os.path.isdir(candidate_dir):
                candidate_dir = os.path.join("/sys/class/backlight", part)
            if os.path.isdir(candidate_dir):
                controller = SystemBacklightController.from_directory(candidate_dir)
                if controller:
                    return controller

        return None

    def set_auto_brightness_enabled(self, enabled: bool, user_triggered: bool = False):
        """Enable or disable auto-brightness."""
        if self._auto_brightness_enabled == enabled and not user_triggered:
            return

        self._auto_brightness_enabled = enabled
        self.auto_brightness_toggled.emit(enabled)

        if enabled:
            # Reset reconnect counter when manually enabling
            self._reconnect_attempts = 0
            
            if not self._ambient_light_monitor:
                if self._auto_brightness_verbose:
                    print("[AutoBrightness] Starting ambient light monitor...", file=sys.stderr, flush=True)
                
                interval = self._auto_brightness_interval_override or self._auto_brightness_interval_ms
                self._ambient_light_monitor = AmbientLightMonitor(
                    camera_index=self._auto_brightness_camera_index,
                    interval_ms=interval,
                    parent=self
                )
                self._ambient_light_monitor.brightnessMeasured.connect(self._on_ambient_brightness_measured)
                self._ambient_light_monitor.errorOccurred.connect(self._on_ambient_light_error)
                self._ambient_light_monitor.cameraIndexResolved.connect(self._on_auto_brightness_camera_resolved)
                self._ambient_light_monitor.start()
                
                # Reset smoothing state
                self._auto_brightness_smoothed = self._current_display_brightness
                self._ambient_brightness_buffer.clear()
                self._auto_brightness_has_sample = False
        else:
            # Stop reconnect timer and reset counter
            self._stop_reconnect_timer()
            self._reconnect_attempts = 0
            
            self._teardown_ambient_monitor()
            # Animate back to manual brightness
            self._apply_brightness(self._manual_brightness, from_auto=False)

    def _teardown_ambient_monitor(self):
        """Stop and cleanup ambient light monitor."""
        if self._ambient_light_monitor:
            if self._auto_brightness_verbose:
                print("[AutoBrightness] Stopping ambient light monitor...", file=sys.stderr, flush=True)
            self._ambient_light_monitor.stop()
            self._ambient_light_monitor.deleteLater()
            self._ambient_light_monitor = None

    def _on_ambient_brightness_measured(self, ambient: float):
        """Handle new ambient brightness measurement."""
        import time
        now = time.time()
        
        # Reset reconnect counter on successful measurement
        self._on_camera_connected_successfully()
        
        # Add to buffer
        self._ambient_brightness_buffer.append(ambient)
        if len(self._ambient_brightness_buffer) > self._ambient_brightness_buffer_size:
            self._ambient_brightness_buffer.pop(0)
            
        # Calculate average ambient brightness
        avg_ambient = sum(self._ambient_brightness_buffer) / len(self._ambient_brightness_buffer)
        
        # Dynamic calibration
        if self._ambient_dynamic_min is None:
            self._ambient_dynamic_min = avg_ambient
            self._ambient_dynamic_max = avg_ambient + 0.001
        else:
            # Expand range
            if avg_ambient < self._ambient_dynamic_min:
                self._ambient_dynamic_min = avg_ambient
            if avg_ambient > self._ambient_dynamic_max:
                self._ambient_dynamic_max = avg_ambient
                
            # Decay range
            self._ambient_dynamic_min += (avg_ambient - self._ambient_dynamic_min) * self._ambient_calibration_decay
            self._ambient_dynamic_max -= (self._ambient_dynamic_max - avg_ambient) * self._ambient_calibration_decay
            
            # Ensure valid range
            if self._ambient_dynamic_max <= self._ambient_dynamic_min:
                self._ambient_dynamic_max = self._ambient_dynamic_min + 0.001

        # Map to target brightness
        target_brightness = self._map_ambient_to_user_brightness(avg_ambient)
        
        # Apply smoothing
        if not self._auto_brightness_has_sample:
            self._auto_brightness_smoothed = target_brightness
            self._auto_brightness_has_sample = True
        else:
            self._auto_brightness_smoothed = (
                self._auto_brightness_smoothing * self._auto_brightness_smoothed +
                (1.0 - self._auto_brightness_smoothing) * target_brightness
            )
            
        # Apply brightness
        self._apply_brightness(self._auto_brightness_smoothed, from_auto=True)
        
        # Logging
        if self._auto_brightness_verbose:
            dt = now - self._last_auto_sample_time
            if dt >= 2.0:  # Log every 2 seconds
                self._last_auto_sample_time = now
                print(f"[AutoBrightness] Ambient={avg_ambient:.4f} (raw={ambient:.4f}) -> Target={target_brightness:.4f} -> Smoothed={self._auto_brightness_smoothed:.4f}", file=sys.stderr, flush=True)

    def _map_ambient_to_user_brightness(self, ambient: float) -> float:
        """Map ambient light level (0.0-1.0) to screen brightness (0.0-1.0)."""
        # Normalize ambient based on dynamic range
        if self._ambient_dynamic_max is None or self._ambient_dynamic_min is None:
            normalized = ambient
        else:
            denom = self._ambient_dynamic_max - self._ambient_dynamic_min
            if denom < 0.0001:
                normalized = 0.5
            else:
                normalized = (ambient - self._ambient_dynamic_min) / denom
                normalized = max(0.0, min(1.0, normalized))
                
        # Apply gamma curve
        curved = math.pow(normalized, 1.0 / self._auto_brightness_curve_gamma)
        
        # Apply min/max constraints
        min_b = self._auto_brightness_min_override if self._auto_brightness_min_override is not None else self._auto_brightness_min
        max_b = self._auto_brightness_max_override if self._auto_brightness_max_override is not None else self._auto_brightness_max
        
        return min_b + (max_b - min_b) * curved

    def _on_ambient_light_error(self, error_code: str):
        """Handle ambient light monitor errors."""
        if self._auto_brightness_verbose:
            print(f"[AutoBrightness] Error: {error_code}", file=sys.stderr, flush=True)
        
        # Non-recoverable errors - disable immediately
        if error_code == "missing_backend":
            self._stop_reconnect_timer()
            self.set_auto_brightness_enabled(False, user_triggered=False)
            self.error_occurred.emit(f"Auto-brightness disabled: {error_code}")
            return
        
        # Recoverable errors - attempt reconnection
        if error_code in ("camera_unavailable", "capture_failed", "unexpected_error"):
            self._attempt_camera_reconnect(error_code)

    def _attempt_camera_reconnect(self, error_code: str):
        """Attempt to reconnect camera with retries."""
        self._reconnect_attempts += 1
        
        if self._reconnect_attempts > self._max_reconnect_attempts:
            if self._auto_brightness_verbose:
                print(f"[AutoBrightness] Max reconnect attempts ({self._max_reconnect_attempts}) reached, disabling auto-brightness", file=sys.stderr, flush=True)
            self._stop_reconnect_timer()
            self._reconnect_attempts = 0
            self.set_auto_brightness_enabled(False, user_triggered=False)
            self.error_occurred.emit(f"Auto-brightness disabled after {self._max_reconnect_attempts} failed reconnection attempts")
            return
        
        if self._auto_brightness_verbose:
            print(f"[AutoBrightness] Reconnect attempt {self._reconnect_attempts}/{self._max_reconnect_attempts} scheduled in {self._reconnect_interval_ms // 1000}s", file=sys.stderr, flush=True)
        
        # Teardown current monitor
        self._teardown_ambient_monitor()
        
        # Schedule reconnect attempt
        if self._reconnect_timer is None:
            self._reconnect_timer = QTimer(self)
            self._reconnect_timer.setSingleShot(True)
            self._reconnect_timer.timeout.connect(self._do_camera_reconnect)
        
        self._reconnect_timer.start(self._reconnect_interval_ms)

    def _do_camera_reconnect(self):
        """Execute camera reconnection attempt."""
        if not self._auto_brightness_enabled:
            # User disabled auto-brightness during wait
            self._reconnect_attempts = 0
            return
        
        if self._auto_brightness_verbose:
            print(f"[AutoBrightness] Attempting camera reconnection ({self._reconnect_attempts}/{self._max_reconnect_attempts})...", file=sys.stderr, flush=True)
        
        # Start new monitor
        interval = self._auto_brightness_interval_override or self._auto_brightness_interval_ms
        self._ambient_light_monitor = AmbientLightMonitor(
            camera_index=self._auto_brightness_camera_index,
            interval_ms=interval,
            parent=self
        )
        self._ambient_light_monitor.brightnessMeasured.connect(self._on_ambient_brightness_measured)
        self._ambient_light_monitor.errorOccurred.connect(self._on_ambient_light_error)
        self._ambient_light_monitor.cameraIndexResolved.connect(self._on_auto_brightness_camera_resolved)
        self._ambient_light_monitor.start()
        
        # Reset smoothing state
        self._auto_brightness_smoothed = self._current_display_brightness
        self._ambient_brightness_buffer.clear()
        self._auto_brightness_has_sample = False

    def _stop_reconnect_timer(self):
        """Stop and cleanup reconnect timer."""
        if self._reconnect_timer:
            self._reconnect_timer.stop()
            self._reconnect_timer.deleteLater()
            self._reconnect_timer = None

    def _on_camera_connected_successfully(self):
        """Reset reconnect counter on successful brightness measurement."""
        if self._reconnect_attempts > 0:
            if self._auto_brightness_verbose:
                print(f"[AutoBrightness] Camera reconnected successfully after {self._reconnect_attempts} attempt(s)", file=sys.stderr, flush=True)
            self._reconnect_attempts = 0

    def _on_auto_brightness_camera_resolved(self, index: int):
        """Handle camera index resolution."""
        if self._auto_brightness_camera_index != index:
            self._auto_brightness_camera_index = index
            if self._auto_brightness_verbose:
                print(f"[AutoBrightness] Camera index updated to {index}", file=sys.stderr, flush=True)

    def _apply_brightness(self, value: float, *, from_auto: bool, animate: bool = True):
        """Apply brightness value to system and UI."""
        value = max(0.05, min(1.0, value))
        
        if not from_auto:
            self._manual_brightness = value
            # If manual adjustment while auto is on, disable auto
            if self._auto_brightness_enabled:
                self.set_auto_brightness_enabled(False, user_triggered=True)
        
        if not animate:
            if self._brightness_animation.state() == QPropertyAnimation.State.Running:
                self._brightness_animation.stop()
            self._apply_brightness_direct(value)
            return

        # Animate change
        if self._brightness_animation.state() == QPropertyAnimation.State.Running:
            self._brightness_animation.stop()
            
        self._brightness_animation.setStartValue(self._current_display_brightness)
        self._brightness_animation.setEndValue(value)
        self._brightness_animation.start()

    def _apply_brightness_direct(self, value: float):
        """Directly apply brightness without animation (called by animation)."""
        self._current_display_brightness = value
        
        # Update cache only if changed significantly (reduces UI invalidations)
        if abs(self._cached_brightness - value) > 0.001:
            self._cached_brightness = value
            # Emit signal for UI updates only when brightness actually changes
            self.brightness_changed.emit(value)
        
        # Apply to system backlight
        self._apply_system_backlight(value)

    def _apply_system_backlight(self, value: float):
        """Apply brightness to system backlight controller."""
        if not self._system_backlight:
            return
            
        try:
            # Apply gamma for better perception
            perceptual_value = math.pow(value, 2.2)
            
            # Log if changed significantly
            if (self._system_backlight_last_ui_log is None or 
                abs(self._system_backlight_last_ui_log - value) > 0.05):
                if self._system_backlight_verbose:
                    print(f"[Backlight] Setting system brightness: {value:.2f} (perceptual: {perceptual_value:.2f})", file=sys.stderr, flush=True)
                self._system_backlight_last_ui_log = value
                
            # Use set_level() which accepts 0.0-1.0 and handles conversion internally
            self._system_backlight.set_level(perceptual_value)
            
        except Exception as e:
            if self._system_backlight_verbose:
                print(f"[Backlight] Error setting brightness: {e}", file=sys.stderr, flush=True)

    def get_brightness(self) -> float:
        """Get cached brightness value (optimized for frequent calls)."""
        return self._cached_brightness

    @property
    def has_system_backlight(self) -> bool:
        """Check if system backlight controller is available."""
        return self._system_backlight is not None

    def is_auto_enabled(self) -> bool:
        return self._auto_brightness_enabled
    
    def cleanup(self):
        """Cleanup resources on shutdown."""
        # Stop reconnect timer
        self._stop_reconnect_timer()
        # Stop ambient light monitor
        self._teardown_ambient_monitor()
