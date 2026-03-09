# Ideato e Realizzato da Pierpaolo Careddu

"""
Threading Utilities — Helper per gestione thread-safe nell'applicazione.

Fornisce:
- Decoratore per eseguire funzioni nel main thread via Signal/Slot
- Timer thread-safe con cancellazione
- Lock context manager con timeout
- Debouncer per evitare chiamate ripetute
"""

import time
import logging
import threading
from typing import Callable, Optional, Any
from functools import wraps

from PySide6.QtCore import QObject, Signal, Slot, QTimer, QMetaObject, Qt

logger = logging.getLogger(__name__)


class MainThreadInvoker(QObject):
    """
    Esegue una callable nel main thread Qt.

    Utile quando un thread secondario deve aggiornare la UI
    o emettere segnali Qt (che devono partire dal main thread).

    Uso:
        invoker = MainThreadInvoker()
        invoker.invoke(lambda: label.setText("Aggiornato"))
    """

    _invoke_signal = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._invoke_signal.connect(self._execute, Qt.ConnectionType.QueuedConnection)

    def invoke(self, func: Callable[[], Any]):
        """Accoda l'esecuzione di func nel main thread."""
        self._invoke_signal.emit(func)

    @Slot(object)
    def _execute(self, func):
        try:
            func()
        except Exception as e:
            logger.error(f"MainThreadInvoker: errore esecuzione: {e}")


class Debouncer:
    """
    Debouncer — Ritarda l'esecuzione finché le chiamate si fermano.

    Se la funzione viene chiamata ripetutamente entro delay_ms,
    solo l'ultima chiamata viene effettivamente eseguita.

    Utile per:
    - Slider che emettono valueChanged ad ogni pixel
    - Ricerche incrementali
    - Resize event

    Uso:
        debounced_save = Debouncer(300, self._save_settings)
        slider.valueChanged.connect(debounced_save)
    """

    def __init__(self, delay_ms: int, callback: Callable, parent: Optional[QObject] = None):
        self._delay_ms = delay_ms
        self._callback = callback
        self._timer = QTimer(parent)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._execute)
        self._last_args: tuple = ()
        self._last_kwargs: dict = {}

    def __call__(self, *args, **kwargs):
        self._last_args = args
        self._last_kwargs = kwargs
        self._timer.stop()
        self._timer.start(self._delay_ms)

    def _execute(self):
        try:
            self._callback(*self._last_args, **self._last_kwargs)
        except Exception as e:
            logger.error(f"Debouncer: errore callback: {e}")

    def cancel(self):
        """Annulla l'esecuzione pendente."""
        self._timer.stop()

    @property
    def is_pending(self) -> bool:
        return self._timer.isActive()


class Throttle:
    """
    Throttle — Limita la frequenza di esecuzione di una funzione.

    A differenza del Debouncer, esegue la prima chiamata immediatamente
    e poi ignora le chiamate successive per min_interval_ms.

    Utile per:
    - Aggiornamenti UI ad alta frequenza (frame, misure)
    - Log rate limiting

    Uso:
        throttled_update = Throttle(100, self._update_display)
        signal.connect(throttled_update)
    """

    def __init__(self, min_interval_ms: int, callback: Callable):
        self._min_interval_s = min_interval_ms / 1000.0
        self._callback = callback
        self._last_call_time: float = 0.0
        self._lock = threading.Lock()

    def __call__(self, *args, **kwargs):
        now = time.perf_counter()
        with self._lock:
            elapsed = now - self._last_call_time
            if elapsed < self._min_interval_s:
                return
            self._last_call_time = now

        try:
            self._callback(*args, **kwargs)
        except Exception as e:
            logger.error(f"Throttle: errore callback: {e}")

    def reset(self):
        with self._lock:
            self._last_call_time = 0.0


class TimeoutLock:
    """
    Lock con timeout — Context manager per acquisire lock con scadenza.

    Uso:
        lock = TimeoutLock()
        with lock.acquire(timeout=2.0) as acquired:
            if acquired:
                # sezione critica
            else:
                logger.warning("Timeout acquisizione lock")
    """

    def __init__(self):
        self._lock = threading.Lock()

    class _LockContext:
        def __init__(self, lock: threading.Lock, timeout: float):
            self._lock = lock
            self._timeout = timeout
            self._acquired = False

        def __enter__(self):
            self._acquired = self._lock.acquire(timeout=self._timeout)
            return self._acquired

        def __exit__(self, exc_type, exc_val, exc_tb):
            if self._acquired:
                self._lock.release()
            return False

    def acquire(self, timeout: float = 5.0):
        """Restituisce un context manager con timeout."""
        return self._LockContext(self._lock, timeout)


class PeriodicWorker(QObject):
    """
    Worker periodico — Esegue una funzione a intervalli regolari.

    Usa QTimer internamente, quindi è main-thread safe.
    Può essere avviato/fermato/riavviato.

    Uso:
        worker = PeriodicWorker(1000, self._poll_status)
        worker.start()
        # ...
        worker.stop()
    """

    def __init__(
        self,
        interval_ms: int,
        callback: Callable[[], None],
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._callback = callback
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._on_tick)
        self._tick_count: int = 0

    @Slot()
    def _on_tick(self):
        self._tick_count += 1
        try:
            self._callback()
        except Exception as e:
            logger.error(f"PeriodicWorker: errore tick #{self._tick_count}: {e}")

    def start(self):
        self._tick_count = 0
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def set_interval(self, interval_ms: int):
        was_active = self._timer.isActive()
        self._timer.stop()
        self._timer.setInterval(interval_ms)
        if was_active:
            self._timer.start()

    @property
    def is_running(self) -> bool:
        return self._timer.isActive()

    @property
    def tick_count(self) -> int:
        return self._tick_count