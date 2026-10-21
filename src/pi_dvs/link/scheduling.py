"""One paced wire request at a time; catalogs cannot monopolize audio bandwidth."""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Condition


class Requests:
    def __init__(self) -> None:
        self._condition = Condition()
        self._waiting: list[tuple[object, bool]] = []
        self._busy = False
        self._audio = 0
        self._progressive = 0
        self._next_send = 0.0
        self._next_catalog = 0.0

    @contextmanager
    def audio(self, *, progressive: bool = False) -> Iterator[None]:
        with self._condition:
            self._audio += 1
            self._progressive += int(progressive)
        try:
            yield
        finally:
            with self._condition:
                self._audio -= 1
                self._progressive -= int(progressive)
                self._condition.notify_all()

    def sent(self, interval: float, *, catalog: bool) -> None:
        """Charge the actual send time while the caller still owns the wire turn."""
        with self._condition:
            now = time.monotonic()
            self._next_send = now + interval
            if catalog:
                self._next_catalog = now + (8 if self._progressive else 2) * interval

    @contextmanager
    def turn(self, check: Callable[[], None], interval: float, *, catalog: bool) -> Iterator[None]:
        token = object()
        item = (token, catalog)
        acquired = False
        with self._condition:
            self._waiting.append(item)
            try:
                while True:
                    check()
                    now = time.monotonic()
                    eligible = next(
                        (
                            entry
                            for entry in self._waiting
                            if not (entry[1] and self._audio and now < self._next_catalog)
                        ),
                        None,
                    )
                    if not self._busy and eligible == item and now >= self._next_send:
                        self._waiting.remove(item)
                        self._busy = acquired = True
                        self._next_send = now + interval
                        if catalog:
                            # Reserve more bandwidth for audio that can already be playing.
                            ratio = 8 if self._progressive else 2
                            self._next_catalog = now + ratio * interval
                        break
                    # Eligibility changes when either pacing deadline expires,
                    # even if another waiter was eligible at the last wake-up.
                    deadlines = [self._next_send]
                    if self._audio:
                        deadlines.append(self._next_catalog)
                    delay = min([0.05] + [at - now for at in deadlines if at > now])
                    self._condition.wait(delay)
            finally:
                if not acquired:
                    self._waiting.remove(item)
                    self._condition.notify_all()
        try:
            yield
        finally:
            with self._condition:
                self._busy = False
                self._condition.notify_all()
