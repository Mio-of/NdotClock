import subprocess
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class RestartHandler(FileSystemEventHandler):
    def __init__(self, cmd):
        self.cmd = cmd
        self.process = None
        self.start_app()

    def start_app(self):
        if self.process:
            self.process.kill()
        self.process = subprocess.Popen(self.cmd)

    def on_modified(self, event):
        if event.src_path.endswith(".py"):
            print("Изменение:", event.src_path)
            self.start_app()

if __name__ == "__main__":
    cmd = ["python3", "debug.py"]  # ← твой PyQt6 файл
    event_handler = RestartHandler(cmd)
    observer = Observer()
    observer.schedule(event_handler, ".", recursive=True)
    observer.start()
    print("Watching for changes…")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        event_handler.process.kill()

    observer.join()