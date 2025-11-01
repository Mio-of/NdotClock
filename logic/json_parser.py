"""Background JSON parsing support to keep the UI responsive."""

import json
from PyQt6.QtCore import QThread, pyqtSignal


class JsonParserThread(QThread):
    """Background thread for parsing JSON to avoid blocking UI"""

    finished = pyqtSignal(object, str)  # (parsed_data, data_type)
    error = pyqtSignal(str, str)  # (error_message, data_type)

    def __init__(self, json_string: str, data_type: str):
        super().__init__()
        self.json_string = json_string
        self.data_type = data_type  # 'location' or 'weather'

    def run(self):
        try:
            data = json.loads(self.json_string)
            self.finished.emit(data, self.data_type)
        except Exception as e:
            self.error.emit(str(e), self.data_type)
