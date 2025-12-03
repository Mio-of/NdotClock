from PyQt6.QtCore import QObject, QTimer, pyqtSignal, QRunnable, QThreadPool
from collections import deque
from typing import Callable

class TaskQueue(QObject):
    """
    Менеджер очереди задач для оптимизации производительности и предотвращения фризов UI.
    Позволяет выполнять задачи последовательно с задержками (для UI) или в фоне.
    """
    task_started = pyqtSignal(str)
    task_finished = pyqtSignal(str)
    all_tasks_finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = deque()
        self._is_running = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._process_next)
        
        self._thread_pool = QThreadPool.globalInstance()
        
        # Интервал по умолчанию между задачами основного потока
        self.default_interval = 50 

    def add_task(self, func: Callable, name: str = "task", delay_ms: int = 0, background: bool = False):
        """
        Добавить задачу в очередь.
        
        :param func: Функция для выполнения
        :param name: Имя задачи (для логов/отладки)
        :param delay_ms: Задержка перед выполнением этой задачи (минимум)
        :param background: Если True, задача будет выполнена в QThreadPool
        """
        self._queue.append({
            'func': func,
            'name': name,
            'delay': delay_ms,
            'background': background
        })
        
        if not self._is_running:
            self.start()

    def start(self):
        """Запустить выполнение очереди."""
        if not self._is_running and self._queue:
            self._is_running = True
            self._process_next()

    def stop(self):
        """Остановить выполнение очереди (очищает очередь)."""
        self._is_running = False
        self._queue.clear()
        self._timer.stop()

    def _process_next(self):
        if not self._queue:
            self._is_running = False
            self.all_tasks_finished.emit()
            return

        task = self._queue.popleft()
        delay = task['delay'] if task['delay'] > 0 else self.default_interval
        
        # Настраиваем выполнение
        if task['background']:
            # Для фоновых задач запускаем сразу, затем ждем delay перед следующей
            self._run_background(task)
            self._timer.start(delay)
        else:
            # Для задач основного потока ждем delay, затем выполняем
            self._schedule_main_task(task, delay)

    def _schedule_main_task(self, task, delay):
        # Используем замыкание для сохранения контекста задачи
        def execute():
            try:
                self.task_started.emit(task['name'])
                task['func']()
                self.task_finished.emit(task['name'])
            except Exception as e:
                print(f"[TaskQueue] Error in task '{task['name']}': {e}")
            
            # Планируем следующую задачу
            if self._is_running:
                # Небольшая пауза для обработки событий UI перед следующим шагом
                QTimer.singleShot(10, self._process_next)

        # Запускаем таймер ожидания перед выполнением
        QTimer.singleShot(delay, execute)

    def _run_background(self, task):
        class Worker(QRunnable):
            def run(self):
                try:
                    task['func']()
                except Exception as e:
                    print(f"[TaskQueue] Background error in '{task['name']}': {e}")

        self.task_started.emit(task['name'])
        self._thread_pool.start(Worker())
