"""Silent demo transport. Elapsed time is supplied by the caller, not a GUI timer.

The public methods are the current engine interface. A real engine will own its
state and report confirmed loads; it must not infer playback from a sent command.
"""

import math
from dataclasses import replace

from pi_dvs.model import DeckState, Status, Track


class DemoEngine:
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

    def load(self, deck: int, track: Track) -> None:
        state = self._deck(deck)
        if state.status == Status.PLAYING:
            raise ValueError("Pause this deck before loading another track")
        self._decks[deck] = DeckState(track=track, status=Status.LOADING)
        self._pending[deck] = self.LOAD_SECONDS

    def unload(self, deck: int) -> None:
        state = self._deck(deck)
        if state.status == Status.PLAYING:
            raise ValueError("Pause this deck before unloading its track")
        self._pending.pop(deck, None)
        self._decks[deck] = DeckState()

    def toggle(self, deck: int) -> None:
        state = self._deck(deck)
        if state.status == Status.PLAYING:
            self._decks[deck] = replace(state, status=Status.PAUSED)
        elif state.track and state.status in (Status.READY, Status.PAUSED):
            position = 0.0 if state.position >= state.track.duration else state.position
            self._decks[deck] = replace(state, status=Status.PLAYING, position=position)

    def advance(self, seconds: float) -> bool:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Elapsed time must be finite and nonnegative")
        before = self.decks
        for deck, state in enumerate(self._decks):
            if state.status == Status.LOADING:
                self._pending[deck] -= seconds
                if self._pending[deck] <= 0:
                    self._pending.pop(deck)
                    assert state.track is not None
                    if state.track.available:
                        self._decks[deck] = replace(state, status=Status.READY)
                    else:
                        self._decks[deck] = replace(
                            state,
                            status=Status.ERROR,
                            error="This demo track is unavailable. Try another track.",
                        )
            elif state.status == Status.PLAYING:
                assert state.track is not None
                position = min(state.position + seconds, state.track.duration)
                self._decks[deck] = replace(
                    state,
                    position=position,
                    status=Status.READY if position >= state.track.duration else Status.PLAYING,
                )
        return self.decks != before
