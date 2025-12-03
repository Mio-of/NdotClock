import os
from typing import Optional, Dict, Tuple
from PyQt6.QtCore import QObject, QTimer, QUrl, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QColor
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtSvg import QSvgRenderer

from logic import JsonParserThread
from ui.utils import get_resource_dir
from ui.popups import ConfirmationPopup

class WeatherManager(QObject):
    weather_updated = pyqtSignal()
    location_updated = pyqtSignal(float, float, str) # lat, lon, city
    error_occurred = pyqtSignal(str) # message

    def __init__(self, parent=None):
        super().__init__(parent)
        self.network_manager = QNetworkAccessManager(self)
        self.weather_data = None
        self.weather_loading = False
        self.weather_status_message = ""
        self.location_lat = None
        self.location_lon = None
        self.current_city = ""
        self.location_loading = False
        
        self.location_parser_thread: Optional[JsonParserThread] = None
        self.weather_parser_thread: Optional[JsonParserThread] = None
        
        self._svg_weather_cache: Dict[Tuple[int, int, int], QPixmap] = {}
        self._svg_weather_cache_max_size = 20
        
        self.current_language = "EN"
        
        self._preload_weather_icons()

    def _tr(self, key: str, **kwargs) -> str:
        """Translate a string using the parent's translation map."""
        if self.parent() and hasattr(self.parent(), '_tr'):
            return self.parent()._tr(key, **kwargs)
        return key

    def set_location(self, lat, lon, city=""):
        self.location_lat = lat
        self.location_lon = lon
        if city:
            self.current_city = city

    def set_language(self, language: str):
        self.current_language = language

    def fetch_location(self):
        """Fetch location from IP geolocation API (HTTPS)"""
        if self.location_loading:
            return

        self.location_loading = True
        # Using ipapi.co with HTTPS for secure geolocation
        url = "https://ipapi.co/json/"
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Mozilla/5.0")
        reply = self.network_manager.get(request)
        reply.finished.connect(lambda: self.handle_location_response(reply))

    def search_city(self, city_name: str):
        """Search for a city using a geocoding API."""
        if self.location_loading:
            return
        self.location_loading = True
        
        # Using a simple geocoding API, replace with your preferred one
        url = f"https://nominatim.openstreetmap.org/search?city={city_name}&format=json&limit=1"
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "NdotClock/1.0")
        reply = self.network_manager.get(request)
        reply.finished.connect(lambda: self.handle_city_search_response(reply))

    def handle_city_search_response(self, reply: QNetworkReply):
        """Handle the response from the city search API."""
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                data = reply.readAll().data()
                self._cleanup_parser_thread('location_parser_thread')
                self.location_parser_thread = JsonParserThread(data, "city_search")
                self.location_parser_thread.finished.connect(self._on_city_search_parsed)
                self.location_parser_thread.error.connect(self._on_json_parse_error)
                self.location_parser_thread.start()
            else:
                self.location_loading = False
                error_msg = f"City Search Error: {reply.errorString()}"
                self.error_occurred.emit(error_msg)
        finally:
            reply.deleteLater()

    def _on_city_search_parsed(self, data: list, data_type: str):
        """Handle parsed city search data."""
        if data_type == "city_search":
            self.location_loading = False
            if data:
                location_data = data[0]
                lat = location_data.get('lat')
                lon = location_data.get('lon')
                name_parts = location_data.get('display_name', '').split(',')
                city = name_parts[0].strip() if name_parts else "Unknown"

                if lat and lon:
                    # Show confirmation popup
                    confirm_popup = ConfirmationPopup(
                        self.parent(),
                        title=self._tr("confirm_location_title"),
                        message=self._tr("confirm_location_message", city=city, country=""),
                        confirm_text=self._tr("confirm_button"),
                        cancel_text=self._tr("cancel_button")
                    )
                    
                    def on_confirmed():
                        self.set_location(float(lat), float(lon), city)
                        self.location_updated.emit(float(lat), float(lon), city)
                        self.fetch_weather()

                    confirm_popup.confirmed.connect(on_confirmed)
                    confirm_popup.show()
                else:
                    self.error_occurred.emit("No coordinates found for this city.")
            else:
                self.error_occurred.emit("City not found.")

    def _cleanup_parser_thread(self, thread_attr: str):
        """Safely cleanup a JSON parser thread to prevent memory leaks."""
        old_thread = getattr(self, thread_attr, None)
        if not old_thread:
            return

        setattr(self, thread_attr, None)

        # Disconnect signals to prevent callbacks after deletion
        try:
            old_thread.finished.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            old_thread.error.disconnect()
        except (RuntimeError, TypeError):
            pass

        # Stop thread if running
        if old_thread.isRunning():
            old_thread.quit()
            old_thread.wait()

        # Schedule deletion
        old_thread.deleteLater()

    def handle_location_response(self, reply: QNetworkReply):
        """Handle location API response"""
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                data = reply.readAll().data()
                # Use thread for parsing
                self._cleanup_parser_thread('location_parser_thread')
                self.location_parser_thread = JsonParserThread(data, "location")
                self.location_parser_thread.finished.connect(self._on_location_parsed)
                self.location_parser_thread.error.connect(self._on_json_parse_error)
                self.location_parser_thread.start()
            else:
                self.location_loading = False
                self.weather_status_message = f"Location Error: {reply.errorString()}"
                self.error_occurred.emit(self.weather_status_message)
        finally:
            reply.deleteLater()

    def _on_location_parsed(self, data: dict, data_type: str):
        """Handle parsed location data"""
        if data_type == "location":
            self.location_loading = False
            lat = data.get('latitude')
            lon = data.get('longitude')
            city = data.get('city')
            if city:
                self.current_city = city
                
            if lat is not None and lon is not None:
                self.location_lat = lat
                self.location_lon = lon
                self.location_updated.emit(lat, lon, self.current_city)
                self.fetch_weather()
            else:
                self.weather_status_message = "Location data incomplete"
                self.error_occurred.emit(self.weather_status_message)

    def fetch_weather(self):
        """Fetch weather data from Open-Meteo API"""
        if self.weather_loading:
            return

        if self.location_lat is None or self.location_lon is None:
            self.fetch_location()
            return

        self.weather_loading = True
        self.weather_status_message = ""
        
        url = f"https://api.open-meteo.com/v1/forecast?latitude={self.location_lat}&longitude={self.location_lon}&current=temperature_2m,is_day,weather_code,wind_speed_10m&wind_speed_unit=ms&timezone=auto"
        
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "NdotClock/1.0")
        reply = self.network_manager.get(request)
        reply.finished.connect(lambda: self.handle_weather_response(reply))

    def handle_weather_response(self, reply: QNetworkReply):
        """Handle weather API response"""
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                data = reply.readAll().data()
                # Use thread for parsing
                self._cleanup_parser_thread('weather_parser_thread')
                self.weather_parser_thread = JsonParserThread(data, "weather")
                self.weather_parser_thread.finished.connect(self._on_weather_parsed)
                self.weather_parser_thread.error.connect(self._on_json_parse_error)
                self.weather_parser_thread.start()
            else:
                self.weather_loading = False
                self.weather_status_message = f"Weather Error: {reply.errorString()}"
                self.error_occurred.emit(self.weather_status_message)
                self.weather_updated.emit()
        finally:
            reply.deleteLater()

    def _on_weather_parsed(self, data: dict, data_type: str):
        """Handle parsed weather data"""
        if data_type == "weather":
            self.weather_loading = False
            current = data.get('current', {})
            if current:
                wind_kmh = current.get('wind_speed_10m', 0)
                self.weather_data = {
                    'temp': current.get('temperature_2m'),
                    'is_day': current.get('is_day') == 1,
                    'code': current.get('weather_code'),
                    'wind': wind_kmh 
                }
                self.weather_status_message = ""
            else:
                self.weather_status_message = "Invalid weather data format"
            
            self.weather_updated.emit()

    def _on_json_parse_error(self, error_message: str, data_type: str):
        """Handle JSON parsing errors"""
        if data_type == "location":
            self.location_loading = False
        elif data_type == "weather":
            self.weather_loading = False
        
        self.weather_status_message = f"Parse Error: {error_message}"
        self.error_occurred.emit(self.weather_status_message)
        self.weather_updated.emit()

    def get_weather_description(self, code: int) -> str:
        """Get localized weather description"""
        weather_codes = {
            0: {"RU": "Ясно", "EN": "Clear sky", "UA": "Ясно"},
            1: {"RU": "Преимущественно ясно", "EN": "Mainly clear", "UA": "Переважно ясно"},
            2: {"RU": "Переменная облачность", "EN": "Partly cloudy", "UA": "Мінлива хмарність"},
            3: {"RU": "Пасмурно", "EN": "Overcast", "UA": "Похмуро"},
            45: {"RU": "Туман", "EN": "Fog", "UA": "Туман"},
            48: {"RU": "Изморозь", "EN": "Depositing rime fog", "UA": "Паморозь"},
            51: {"RU": "Легкая морось", "EN": "Light drizzle", "UA": "Легка мряка"},
            53: {"RU": "Умеренная морось", "EN": "Moderate drizzle", "UA": "Помірна мряка"},
            55: {"RU": "Сильная морось", "EN": "Dense drizzle", "UA": "Сильна мряка"},
            61: {"RU": "Слабый дождь", "EN": "Slight rain", "UA": "Слабкий дощ"},
            63: {"RU": "Умеренный дождь", "EN": "Moderate rain", "UA": "Помірний дощ"},
            65: {"RU": "Сильный дождь", "EN": "Heavy rain", "UA": "Сильний дощ"},
            71: {"RU": "Слабый снег", "EN": "Slight snow fall", "UA": "Слабкий сніг"},
            73: {"RU": "Умеренный снег", "EN": "Moderate snow fall", "UA": "Помірний сніг"},
            75: {"RU": "Сильный снег", "EN": "Heavy snow fall", "UA": "Сильний сніг"},
            77: {"RU": "Снежные зерна", "EN": "Snow grains", "UA": "Снігові зерна"},
            80: {"RU": "Слабый ливень", "EN": "Slight rain showers", "UA": "Слабка злива"},
            81: {"RU": "Умеренный ливень", "EN": "Moderate rain showers", "UA": "Помірна злива"},
            82: {"RU": "Сильный ливень", "EN": "Violent rain showers", "UA": "Сильна злива"},
            85: {"RU": "Слабый снег с дождем", "EN": "Slight snow showers", "UA": "Слабкий сніг з дощем"},
            86: {"RU": "Сильный снег с дождем", "EN": "Heavy snow showers", "UA": "Сильний сніг з дощем"},
            95: {"RU": "Гроза", "EN": "Thunderstorm", "UA": "Гроза"},
            96: {"RU": "Гроза с градом", "EN": "Thunderstorm with slight hail", "UA": "Гроза з градом"},
            99: {"RU": "Гроза с сильным градом", "EN": "Thunderstorm with heavy hail", "UA": "Гроза з сильним градом"}
        }

        desc_dict = weather_codes.get(code, {"RU": "Неизвестно", "EN": "Unknown", "UA": "Невідомо"})
        return desc_dict.get(self.current_language, desc_dict["EN"])

    def _preload_weather_icons(self):
        """Fix: Preload all weather SVG icons for ARM optimization"""
        resources_dir = get_resource_dir("resources")
        icon_names = [
            "clear day.svg", "clear night.svg",
            "partly cloudy day.svg", "partly cloudy night.svg",
            "cloudy day.svg", "showers day.svg", "no data.svg"
        ]

        # Preload with typical size
        preload_height = 80
        for icon_name in icon_names:
            icon_path = os.path.join(resources_dir, icon_name)
            if os.path.exists(icon_path):
                try:
                    svg_renderer = QSvgRenderer(icon_path)
                    if svg_renderer.isValid():
                        svg_size = svg_renderer.defaultSize()
                        aspect_ratio = svg_size.width() / max(1, svg_size.height())
                        icon_width = int(preload_height * aspect_ratio)

                        pixmap = QPixmap(icon_width, preload_height)
                        pixmap.fill(Qt.GlobalColor.transparent)
                        pix_painter = QPainter(pixmap)
                        pix_painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                        svg_renderer.render(pix_painter, QRectF(0, 0, icon_width, preload_height))
                        pix_painter.end()
                except Exception:
                    pass

    def get_weather_icon_path(self, code: int, is_day: int) -> str:
        """Get SVG icon path for weather code"""
        resources_dir = get_resource_dir("resources")

        # Map weather codes to icon filenames
        if code in [0, 1]:  # Clear / Mainly clear
            icon_name = "clear day.svg" if is_day else "clear night.svg"
        elif code == 2:  # Partly cloudy
            icon_name = "partly cloudy day.svg" if is_day else "partly cloudy night.svg"
        elif code == 3:  # Overcast
            icon_name = "cloudy day.svg"
        elif code in [45, 48]:  # Fog
            icon_name = "cloudy day.svg"
        elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]:  # Rain
            icon_name = "showers day.svg"
        elif code in [71, 73, 75, 77, 85, 86]:  # Snow
            icon_name = "showers day.svg"  # Using showers for snow for now or add snow icon
        elif code in [95, 96, 99]:  # Thunderstorm
            icon_name = "showers day.svg"
        else:
            icon_name = "no data.svg"

        return os.path.join(resources_dir, icon_name)

    def get_weather_pixmap(self, code: int, is_day: int, size: int) -> QPixmap:
        cache_key = (code, int(is_day), int(size))
        if cache_key in self._svg_weather_cache:
            # Move to end (LRU)
            val = self._svg_weather_cache.pop(cache_key)
            self._svg_weather_cache[cache_key] = val
            return val

        icon_path = self.get_weather_icon_path(code, is_day)
        if not os.path.exists(icon_path):
             return QPixmap()

        renderer = QSvgRenderer(icon_path)
        if not renderer.isValid():
             return QPixmap()
             
        # Calculate aspect ratio to prevent stretching
        svg_size = renderer.defaultSize()
        aspect_ratio = svg_size.width() / max(1, svg_size.height())
        width = int(size * aspect_ratio)
             
        pixmap = QPixmap(width, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, width, size))
        painter.end()
        
        # Cache
        if len(self._svg_weather_cache) >= self._svg_weather_cache_max_size:
            self._svg_weather_cache.pop(next(iter(self._svg_weather_cache)))
        self._svg_weather_cache[cache_key] = pixmap
        
        return pixmap
