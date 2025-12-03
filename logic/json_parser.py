"""Background JSON parsing support to keep the UI responsive."""

import json
import logging
from typing import Any
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class JsonParserThread(QThread):
    """Background thread for parsing JSON to avoid blocking UI.
    
    Attributes:
        finished: Signal emitted with (parsed_data, data_type) on success
        error: Signal emitted with (error_message, data_type) on failure
    """

    finished = pyqtSignal(object, str)  # (parsed_data, data_type)
    error = pyqtSignal(str, str)  # (error_message, data_type)

    def __init__(self, json_string: str, data_type: str) -> None:
        """Initialize JSON parser thread.
        
        Args:
            json_string: JSON string to parse
            data_type: Type identifier ('location', 'weather', etc.)
        """
        super().__init__()
        self.json_string = json_string
        self.data_type = data_type

    def run(self) -> None:
        """Parse JSON in background thread."""
        try:
            data: Any = json.loads(self.json_string)
            logger.debug(f"Successfully parsed {self.data_type} JSON")
            self.finished.emit(data, self.data_type)
        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON format: {e}"
            logger.error(f"JSON parse error in {self.data_type}: {error_msg}")
            self.error.emit(error_msg, self.data_type)
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            logger.exception(f"Unexpected error parsing {self.data_type} JSON")
            self.error.emit(error_msg, self.data_type)
