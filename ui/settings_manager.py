import json
import os
from typing import Dict, Any, List
from PyQt6.QtGui import QColor
from ui.animations import SlideType

class SettingsManager:
    def __init__(self, config_dir: str):
        self.settings_file = os.path.join(config_dir, 'ndot_clock_settings.json')
        self.default_settings = {
            'user_brightness': 0.8,
            'digit_color': (246, 246, 255),
            'background_color': (0, 0, 0),
            'colon_color': (220, 40, 40),
            'language': 'RU',
            'slides': [],
            'location': {'lat': None, 'lon': None},
            'fullscreen': False,
            'auto_brightness_enabled': False,
            'auto_brightness_camera': 0,
            'auto_brightness_interval_ms': 1000,
            'auto_brightness_min': 0.0,
            'auto_brightness_max': 1.0,
            'window_position': {'x': 100, 'y': 100},
        }

    def load_settings(self) -> Dict[str, Any]:
        """Load and validate settings, returning a dictionary with native types"""
        settings = self.default_settings.copy()
        
        print(f"[SettingsManager] Loading from: {self.settings_file}")
        print(f"[SettingsManager] File exists: {os.path.exists(self.settings_file)}")
        
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    print(f"[SettingsManager] Loaded JSON keys: {list(loaded.keys())}")
                    print(f"[SettingsManager] fullscreen in file: {loaded.get('fullscreen')}")
                    print(f"[SettingsManager] auto_brightness_enabled in file: {loaded.get('auto_brightness_enabled')}")
                    # Update only keys that exist in loaded settings to preserve defaults
                    # But here we want to override defaults with loaded values
                    settings.update(loaded)
            except Exception as e:
                print(f"[SettingsManager] Error loading settings: {e}")

        # Validate and convert types
        validated = {}
        
        # Brightness
        validated['user_brightness'] = max(0.0, min(1.0, float(settings.get('user_brightness', 0.8))))
        
        # Auto brightness
        validated['auto_brightness_enabled'] = bool(settings.get('auto_brightness_enabled', False))
        validated['auto_brightness_camera'] = int(settings.get('auto_brightness_camera', 0))
        validated['auto_brightness_interval_ms'] = max(250, int(settings.get('auto_brightness_interval_ms', 1000)))
        
        auto_min = float(settings.get('auto_brightness_min', 0.0))
        auto_max = float(settings.get('auto_brightness_max', 1.0))
        if auto_min > auto_max:
            auto_min, auto_max = auto_max, auto_min
        validated['auto_brightness_min'] = max(0.0, min(1.0, auto_min))
        validated['auto_brightness_max'] = max(validated['auto_brightness_min'], min(1.0, auto_max))

        # Colors
        validated['digit_color'] = QColor(*settings.get('digit_color', (246, 246, 255)))
        validated['background_color'] = QColor(*settings.get('background_color', (0, 0, 0)))
        validated['colon_color'] = QColor(*settings.get('colon_color', (220, 40, 40)))
        
        # General
        validated['language'] = settings.get('language', 'RU')
        validated['fullscreen'] = settings.get('fullscreen', False)
        validated['location'] = settings.get('location', {'lat': None, 'lon': None})
        validated['window_position'] = settings.get('window_position', {'x': 100, 'y': 100})
        
        # Slides
        slides_data = settings.get('slides', [])
        validated_slides = []
        for s in slides_data:
            try:
                slide_type = SlideType(s['type'])
                # Skip ADD slides from saved data - we'll add it at the end
                if slide_type != SlideType.ADD:
                    validated_slides.append({
                        'type': slide_type,
                        'data': s.get('data', {})
                    })
            except (ValueError, KeyError):
                continue
        
        # If no slides, add default clock slide
        if not validated_slides:
            validated_slides = [{'type': SlideType.CLOCK, 'data': {}}]
        
        # Always add ADD slide at the end
        validated_slides.append({'type': SlideType.ADD, 'data': {}})
            
        validated['slides'] = validated_slides
        
        return validated

    def save_settings(self, settings: Dict[str, Any]):
        """Save settings dictionary to file"""
        # Convert QColor and Enums back to serializable formats
        serializable = settings.copy()
        
        if isinstance(serializable.get('digit_color'), QColor):
            c = serializable['digit_color']
            serializable['digit_color'] = (c.red(), c.green(), c.blue())
            
        if isinstance(serializable.get('background_color'), QColor):
            c = serializable['background_color']
            serializable['background_color'] = (c.red(), c.green(), c.blue())
            
        if isinstance(serializable.get('colon_color'), QColor):
            c = serializable['colon_color']
            serializable['colon_color'] = (c.red(), c.green(), c.blue())
            
        # Convert slides (exclude ADD slides - they're added automatically)
        if 'slides' in serializable:
            serializable['slides'] = [
                {'type': s['type'].value, 'data': s['data']} 
                for s in serializable['slides']
                if s['type'] != SlideType.ADD
            ]
            
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(serializable, f, indent=4, ensure_ascii=False)
        except Exception:
            pass
