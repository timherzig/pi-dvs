"""Silent vinyl simulation. Elapsed time is supplied by the caller.

Needle and platter inputs are explicit simulated values, not hardware detection.
A real engine must report confirmed transport, position, and load state.
"""

import math
from dataclasses import replace
from typing import Protocol

from pi_dvs.model import DeckState, Status, Track


def _follow_vinyl(state: DeckState) -> DeckState:
    if state.track is None or state.status in (Status.LOADING, Status.ERROR):
        return state
    if state.position >= state.track.duration:
        status = Status.FINISHED
    elif not state.needle_down:
        status = Status.READY
    elif not state.platter_spinning:
        status = Status.STOPPED
    else:
        status = Status.PLAYING
    return replace(state, status=status)


class Engine(Protocol):
    simulation: bool

    @property
    def decks(self) -> tuple[DeckState, ...]: ...
    def load(self, deck: int, track: Track, *, generation: int | None = None) -> None: ...
    def unload(self, deck: int) -> None: ...
    def advance(self, seconds: float) -> bool: ...
    def close(self) -> None: ...


class DemoEngine:
    simulation = True

    def close(self) -> None:
        pass

    LOAD_SECONDS = 0.35

    def __init__(self) -> None:
        self._decks = [DeckState(), DeckState()]
        self._pending: dict[int, float] = {}

    @property
    def decks(self) -> tuple[DeckState, ...]:
        return tuple(self._decks)

    def _deck(self, deck: int) -> DeckState:
        if deck not in (0, 1):
            raise ValueError("Deck must be 0 (A) or 1 (B)")
        return self._decks[deck]

    def load(self, deck: int, track: Track, *, generation: int | None = None) -> None:
        state = self._deck(deck)
        if not state.can_change_track:
            raise ValueError("Stop the record or lift the needle before changing tracks")
        self._decks[deck] = replace(
            state, track=track, status=Status.LOADING, position=0.0, error=""
        )
        self._pending[deck] = self.LOAD_SECONDS

    def unload(self, deck: int) -> None:
        state = self._deck(deck)
        if not state.can_change_track:
            raise ValueError("Stop the record or lift the needle before changing tracks")
        self._pending.pop(deck, None)
        self._decks[deck] = replace(state, track=None, status=Status.EMPTY, position=0.0, error="")

    def set_needle(self, deck: int, down: bool) -> None:
        self._decks[deck] = _follow_vinyl(replace(self._deck(deck), needle_down=down))

    def set_platter(self, deck: int, spinning: bool) -> None:
        self._decks[deck] = _follow_vinyl(replace(self._deck(deck), platter_spinning=spinning))

    def advance(self, seconds: float) -> bool:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Elapsed time must be finite and nonnegative")
        before = self.decks
        for deck, state in enumerate(self._decks):
            playing_seconds = seconds
            if state.status == Status.LOADING:
                remaining = self._pending[deck]
                if seconds < remaining:
                    self._pending[deck] = remaining - seconds
                    continue
                self._pending.pop(deck)
                assert state.track is not None
                if state.track.available:
                    state = _follow_vinyl(replace(state, status=Status.READY))
                else:
                    state = replace(
                        state,
                        status=Status.ERROR,
                        error="This demo track is unavailable. Try another track.",
                    )
                playing_seconds = seconds - remaining
            if state.status == Status.PLAYING:
                assert state.track is not None
                state = _follow_vinyl(
                    replace(
                        state, position=min(state.position + playing_seconds, state.track.duration)
                    )
                )
            self._decks[deck] = state
        return self.decks != before
