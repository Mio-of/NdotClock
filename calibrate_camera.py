#!/usr/bin/env python3
"""
Camera Calibration Tool for Auto-Brightness

This script helps calibrate the camera for auto-brightness by measuring
ambient light values in different conditions.

Usage:
    python calibrate_camera.py

Instructions will appear on screen.
"""

import sys
import time
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    print("=" * 60)
    print("  CAMERA CALIBRATION FOR AUTO-BRIGHTNESS")
    print("=" * 60)
    print()
    
    # Check dependencies
    try:
        import numpy as np
    except ImportError:
        print("ERROR: NumPy not installed. Run: pip install numpy")
        return 1
    
    # Try to import camera backends
    cv2 = None
    picamera2 = None
    
    try:
        import cv2 as cv2_module
        cv2 = cv2_module
        print("✓ OpenCV available")
    except ImportError:
        print("✗ OpenCV not available")
    
    try:
        from picamera2 import Picamera2
        picamera2 = Picamera2
        print("✓ Picamera2 available")
    except ImportError:
        print("✗ Picamera2 not available")
    
    if cv2 is None and picamera2 is None:
        print("\nERROR: No camera backend available!")
        print("Install OpenCV (pip install opencv-python) or Picamera2")
        return 1
    
    print()
    print("-" * 60)
    print("Starting camera...")
    print("-" * 60)
    
    # Try to open camera
    capture = None
    using_picamera2 = False
    
    # Try Picamera2 first on Raspberry Pi
    if picamera2 is not None:
        try:
            cam = picamera2()
            config = cam.create_preview_configuration(
                main={"size": (640, 480), "format": "RGB888"}
            )
            cam.configure(config)
            cam.start()
            time.sleep(1)  # Let camera warm up
            capture = cam
            using_picamera2 = True
            print("✓ Picamera2 camera opened successfully")
        except Exception as e:
            print(f"✗ Picamera2 failed: {e}")
    
    # Try OpenCV as fallback
    if capture is None and cv2 is not None:
        for idx in range(3):
            try:
                cap = cv2.VideoCapture(idx)
                if cap.isOpened():
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        capture = cap
                        print(f"✓ OpenCV camera {idx} opened successfully")
                        break
                cap.release()
            except Exception as e:
                print(f"✗ OpenCV camera {idx} failed: {e}")
    
    if capture is None:
        print("\nERROR: Could not open any camera!")
        return 1
    
    def read_frame():
        """Read a frame from the camera."""
        if using_picamera2:
            return capture.capture_array()
        else:
            ret, frame = capture.read()
            return frame if ret else None
    
    def calculate_brightness(frame):
        """Calculate mean brightness of a frame (0.0 - 1.0)."""
        if frame is None:
            return None
        if frame.ndim == 3:
            if cv2 is not None:
                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY if using_picamera2 else cv2.COLOR_BGR2GRAY)
            else:
                gray = np.mean(frame, axis=2)
        else:
            gray = frame
        return float(np.mean(gray)) / 255.0
    
    def cleanup():
        """Close camera."""
        if using_picamera2:
            capture.stop()
        else:
            capture.release()
    
    # Calibration values
    min_value = 1.0
    max_value = 0.0
    samples = []
    
    print()
    print("=" * 60)
    print("  CALIBRATION INSTRUCTIONS")
    print("=" * 60)
    print()
    print("The camera will measure ambient light values.")
    print("Current value will be displayed in real-time.")
    print()
    print("STEP 1: DARK CALIBRATION")
    print("  → Cover the camera completely with your hand or cloth")
    print("  → Wait for the value to stabilize")
    print("  → Press ENTER when ready")
    print()
    
    input("Press ENTER to start dark calibration...")
    print()
    print("Measuring DARK values (10 seconds)...")
    print("Keep the camera covered!")
    print()
    
    dark_values = []
    start = time.time()
    while time.time() - start < 10:
        frame = read_frame()
        brightness = calculate_brightness(frame)
        if brightness is not None:
            dark_values.append(brightness)
            min_value = min(min_value, brightness)
            bar = "█" * int(brightness * 50)
            print(f"\r  Brightness: {brightness:.4f} [{bar:<50}]", end="", flush=True)
        time.sleep(0.2)
    
    dark_avg = sum(dark_values) / len(dark_values) if dark_values else 0
    dark_min = min(dark_values) if dark_values else 0
    dark_max = max(dark_values) if dark_values else 0
    
    print()
    print()
    print(f"  DARK results:")
    print(f"    Min: {dark_min:.4f}")
    print(f"    Max: {dark_max:.4f}")
    print(f"    Avg: {dark_avg:.4f}")
    print()
    
    print("-" * 60)
    print()
    print("STEP 2: BRIGHT CALIBRATION")
    print("  → Shine a flashlight directly at the camera")
    print("  → Or point the camera at a bright light source")
    print("  → Wait for the value to stabilize")
    print("  → Press ENTER when ready")
    print()
    
    input("Press ENTER to start bright calibration...")
    print()
    print("Measuring BRIGHT values (10 seconds)...")
    print("Keep the light shining!")
    print()
    
    bright_values = []
    start = time.time()
    while time.time() - start < 10:
        frame = read_frame()
        brightness = calculate_brightness(frame)
        if brightness is not None:
            bright_values.append(brightness)
            max_value = max(max_value, brightness)
            bar = "█" * int(brightness * 50)
            print(f"\r  Brightness: {brightness:.4f} [{bar:<50}]", end="", flush=True)
        time.sleep(0.2)
    
    bright_avg = sum(bright_values) / len(bright_values) if bright_values else 0
    bright_min = min(bright_values) if bright_values else 0
    bright_max = max(bright_values) if bright_values else 0
    
    print()
    print()
    print(f"  BRIGHT results:")
    print(f"    Min: {bright_min:.4f}")
    print(f"    Max: {bright_max:.4f}")
    print(f"    Avg: {bright_avg:.4f}")
    print()
    
    print("-" * 60)
    print()
    print("STEP 3: NORMAL ROOM CALIBRATION")
    print("  → Point camera at normal room lighting")
    print("  → This is your typical usage environment")
    print("  → Press ENTER when ready")
    print()
    
    input("Press ENTER to start room calibration...")
    print()
    print("Measuring ROOM values (10 seconds)...")
    print()
    
    room_values = []
    start = time.time()
    while time.time() - start < 10:
        frame = read_frame()
        brightness = calculate_brightness(frame)
        if brightness is not None:
            room_values.append(brightness)
            bar = "█" * int(brightness * 50)
            print(f"\r  Brightness: {brightness:.4f} [{bar:<50}]", end="", flush=True)
        time.sleep(0.2)
    
    room_avg = sum(room_values) / len(room_values) if room_values else 0
    room_min = min(room_values) if room_values else 0
    room_max = max(room_values) if room_values else 0
    
    print()
    print()
    print(f"  ROOM results:")
    print(f"    Min: {room_min:.4f}")
    print(f"    Max: {room_max:.4f}")
    print(f"    Avg: {room_avg:.4f}")
    print()
    
    print("-" * 60)
    print()
    print("STEP 4: DARK ROOM CALIBRATION")
    print("  → Turn off all lights in the room")
    print("  → DO NOT cover the camera - just darken the room")
    print("  → Close curtains/blinds if possible")
    print("  → Wait for eyes and camera to adjust")
    print("  → Press ENTER when ready")
    print()
    
    input("Press ENTER to start dark room calibration...")
    print()
    print("Measuring DARK ROOM values (10 seconds)...")
    print("Keep the room dark!")
    print()
    
    darkroom_values = []
    start = time.time()
    while time.time() - start < 10:
        frame = read_frame()
        brightness = calculate_brightness(frame)
        if brightness is not None:
            darkroom_values.append(brightness)
            min_value = min(min_value, brightness)
            bar = "█" * int(brightness * 50)
            print(f"\r  Brightness: {brightness:.4f} [{bar:<50}]", end="", flush=True)
        time.sleep(0.2)
    
    darkroom_avg = sum(darkroom_values) / len(darkroom_values) if darkroom_values else 0
    darkroom_min = min(darkroom_values) if darkroom_values else 0
    darkroom_max = max(darkroom_values) if darkroom_values else 0
    
    print()
    print()
    print(f"  DARK ROOM results:")
    print(f"    Min: {darkroom_min:.4f}")
    print(f"    Max: {darkroom_max:.4f}")
    print(f"    Avg: {darkroom_avg:.4f}")
    print()
    
    # Cleanup
    cleanup()
    
    # Results
    print("=" * 60)
    print("  CALIBRATION RESULTS")
    print("=" * 60)
    print()
    print(f"  Camera Range Detected:")
    print(f"    Minimum (dark):     {min_value:.4f}")
    print(f"    Maximum (bright):   {max_value:.4f}")
    print(f"    Range:              {max_value - min_value:.4f}")
    print()
    print(f"  Lighting Conditions Summary:")
    print(f"    Covered (black):    {dark_avg:.4f}")
    print(f"    Dark room:          {darkroom_avg:.4f}")
    print(f"    Normal room:        {room_avg:.4f}")
    print(f"    Bright light:       {bright_avg:.4f}")
    print()
    
    # Recommendations
    print("-" * 60)
    print("  ANALYSIS")
    print("-" * 60)
    print()
    
    if max_value - min_value < 0.1:
        print("  ⚠ WARNING: Very narrow range detected!")
        print("    The camera may not be suitable for auto-brightness.")
        print("    Consider:")
        print("    - Checking camera orientation")
        print("    - Using a different camera")
        print("    - Adjusting camera exposure settings")
        print()
    
    # Calculate calibration values
    # Use slightly wider margins for robustness
    cam_min = max(0.0, dark_avg * 0.9)   # Slightly below dark average
    cam_max = min(1.0, bright_avg * 1.1)  # Slightly above bright average
    
    if cam_max <= cam_min:
        cam_min = min_value
        cam_max = max_value
    
    cam_darkroom = round(darkroom_avg, 4)
    
    print(f"  Calibration values to be saved:")
    print(f"    camera_ambient_min:      {cam_min:.4f}")
    print(f"    camera_ambient_max:      {cam_max:.4f}")
    print(f"    camera_ambient_darkroom: {cam_darkroom:.4f}")
    print()
    
    # Save to settings file
    print("-" * 60)
    print("  SAVING TO SETTINGS")
    print("-" * 60)
    print()
    
    settings_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'resources',
        'ndot_clock_settings.json'
    )
    
    # Load existing settings or create new
    settings = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                import json
                settings = json.load(f)
            print(f"  ✓ Loaded existing settings from:")
            print(f"    {settings_path}")
        except Exception as e:
            print(f"  ⚠ Could not load settings: {e}")
            print("    Will create new settings file.")
    else:
        print(f"  Creating new settings file:")
        print(f"    {settings_path}")
        # Ensure resources directory exists
        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    
    # Update calibration values
    settings['camera_ambient_min'] = round(cam_min, 4)
    settings['camera_ambient_max'] = round(cam_max, 4)
    settings['camera_ambient_darkroom'] = cam_darkroom
    
    # Save settings
    try:
        import json
        with open(settings_path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        print()
        print(f"  ✓ Calibration saved successfully!")
        print()
        print(f"  Values written:")
        print(f'    "camera_ambient_min": {cam_min:.4f}')
        print(f'    "camera_ambient_max": {cam_max:.4f}')
        print(f'    "camera_ambient_darkroom": {cam_darkroom}')
    except Exception as e:
        print()
        print(f"  ✗ ERROR: Could not save settings: {e}")
        print()
        print("  You can manually add these to your settings:")
        print(f'    "camera_ambient_min": {cam_min:.4f},')
        print(f'    "camera_ambient_max": {cam_max:.4f},')
        print(f'    "camera_ambient_darkroom": {cam_darkroom}')
    
    print()
    print("=" * 60)
    print("  Calibration complete!")
    print("  Restart the application to apply new settings.")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nCalibration cancelled.")
        sys.exit(1)
