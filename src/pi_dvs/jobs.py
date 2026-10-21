"""Small cancellable worker boundary for removable-media I/O."""

import logging
from collections.abc import Callable
from enum import Enum
from queue import Empty, Full, Queue
from threading import Event, Thread

from PySide6.QtCore import QObject, Qt, Signal, Slot

from pi_dvs.rekordbox.records import ImportCancelled

logger = logging.getLogger(__name__)


class JobKind(Enum):
    IMPORT = (None, 2)
    DECK_A = (0, 1)
    DECK_B = (1, 1)
    COVER_A = (0, 1, True)
    COVER_B = (1, 1, True)

    def __init__(self, deck: int | None, workers: int, cover: bool = False) -> None:
        self.deck = deck
        self.workers = workers
        self.cover = cover

    @classmethod
    def for_deck(cls, deck: int) -> "JobKind":
        return {0: cls.DECK_A, 1: cls.DECK_B}[deck]

    @classmethod
    def for_cover(cls, deck: int) -> "JobKind":
        return {0: cls.COVER_A, 1: cls.COVER_B}[deck]


class Jobs(QObject):
    completed = Signal(object, object, str)
    _finished = Signal(object, int, object, str)

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._pending: dict[JobKind, tuple[int, Event]] = {}
        self._generation = 0
        self._closed = False
        self._stop = Event()
        self._queues: dict[JobKind, Queue[tuple[int, Event, Callable[[Event], object]]]] = {}
        self._finished.connect(self._receive, Qt.ConnectionType.QueuedConnection)

    def cancel(self, key: JobKind) -> None:
        pending = self._pending.pop(key, None)
        if pending:
            pending[1].set()

    def submit(self, key: JobKind, work: Callable[[Event], object]) -> None:
        if self._closed:
            return
        self.cancel(key)
        self._generation += 1
        generation, cancelled = self._generation, Event()
        self._pending[key] = (generation, cancelled)
        if key not in self._queues:
            queue: Queue[tuple[int, Event, Callable[[Event], object]]] = Queue(maxsize=1)
            self._queues[key] = queue
            # Two import readers let a new source progress while an old device stalls.
            # The pending queue holds only the newest request; thread count is bounded.
            for index in range(key.workers):
                Thread(
                    target=self._run,
                    args=(key, queue),
                    name=f"pi-dvs-{key.name.lower()}-{index}",
                    daemon=True,
                ).start()
        queue = self._queues[key]
        try:
            queue.put_nowait((generation, cancelled, work))
        except Full:
            try:
                queue.get_nowait()
            except Empty:
                pass  # A worker picked it up between the two operations.
            queue.put_nowait((generation, cancelled, work))

    def _run(
        self, key: JobKind, queue: Queue[tuple[int, Event, Callable[[Event], object]]]
    ) -> None:
        while not self._stop.is_set():
            try:
                generation, cancelled, work = queue.get(timeout=0.2)
            except Empty:
                continue
            if cancelled.is_set():
                continue
            result: object = None
            error = ""
            try:
                result = work(cancelled)
            except ImportCancelled:
                continue
            except (OSError, ValueError) as failure:
                error = str(failure)
            except Exception:
                # A worker must report failure instead of leaving the UI busy forever.
                # Preserve the traceback; expected media errors use the branch above.
                logger.exception("Unexpected failure in %s", key)
                error = "Unexpected library error. See the application log and retry."
            if not cancelled.is_set():
                self._finished.emit(key, generation, result, error)

    @Slot(object, int, object, str)
    def _receive(self, key: JobKind, generation: int, result: object, error: str) -> None:
        pending = self._pending.get(key)
        if self._closed or not pending or pending[0] != generation:
            return
        self._pending.pop(key)
        self.completed.emit(key, result, error)

    def close(self) -> None:
        self._closed = True
        self._stop.set()
        for _, event in self._pending.values():
            event.set()
        self._pending.clear()
