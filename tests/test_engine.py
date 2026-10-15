import pytest

from pi_dvs.engine import DemoEngine
from pi_dvs.model import Status, Track


@pytest.fixture
def track():
    return Track("one", "One", "Artist", 10)


def test_load_is_pending_until_completed_and_decks_are_independent(track):
    engine = DemoEngine()
    engine.load(0, track)
    assert engine.decks[0].status == Status.LOADING
    assert engine.decks[1].status == Status.EMPTY
    engine.advance(0.1)
    assert engine.decks[0].status == Status.LOADING
    engine.advance(0.3)
    engine.toggle(0)
    engine.advance(2)
    assert engine.decks[0].position == 2
    engine.load(1, Track("two", "Two", "Artist", 20))
    engine.advance(0.5)
    assert engine.decks[0].position == 2.5
    assert engine.decks[1].status == Status.READY
    assert engine.decks[1].position == 0


def test_pause_resume_end_and_replay(track):
    engine = DemoEngine()
    engine.load(0, track)
    engine.advance(1)
    engine.toggle(0)
    engine.advance(4)
    engine.toggle(0)
    engine.advance(100)
    assert engine.decks[0].status == Status.PAUSED
    assert engine.decks[0].position == 4
    engine.toggle(0)
    engine.advance(100)
    assert engine.decks[0].position == track.duration
    assert engine.decks[0].status == Status.READY
    engine.toggle(0)
    assert engine.decks[0].position == 0
    assert engine.decks[0].status == Status.PLAYING


def test_replacing_or_unloading_pending_load_cannot_resurrect_old_track(track):
    engine = DemoEngine()
    other = Track("two", "Two", "Artist", 20)
    engine.load(0, track)
    engine.advance(0.2)
    engine.load(0, other)
    engine.advance(0.2)
    assert engine.decks[0].status == Status.LOADING
    engine.advance(0.2)
    assert engine.decks[0].track == other
    engine.load(0, track)
    engine.unload(0)
    engine.advance(1)
    assert engine.decks[0].status == Status.EMPTY
    assert engine.decks[0].track is None


def test_failed_load_can_be_recovered_and_has_no_transport(track):
    engine = DemoEngine()
    engine.load(0, Track("missing", "Missing", "Artist", 10, available=False))
    engine.toggle(0)
    assert engine.decks[0].status == Status.LOADING
    engine.advance(1)
    assert engine.decks[0].status == Status.ERROR
    assert engine.decks[0].error
    engine.toggle(0)
    assert engine.decks[0].status == Status.ERROR
    engine.load(0, track)
    engine.advance(1)
    assert engine.decks[0].status == Status.READY
    assert engine.decks[0].error == ""


def test_playing_deck_cannot_be_replaced_or_unloaded(track):
    engine = DemoEngine()
    engine.load(0, track)
    engine.advance(1)
    engine.toggle(0)
    before = engine.decks
    with pytest.raises(ValueError, match="Pause"):
        engine.load(0, Track("two", "Two", "Artist", 20))
    with pytest.raises(ValueError, match="Pause"):
        engine.unload(0)
    assert engine.decks == before


@pytest.mark.parametrize("deck", [-1, 2])
def test_invalid_deck_cannot_modify_another_deck(deck, track):
    engine = DemoEngine()
    with pytest.raises(ValueError):
        engine.load(deck, track)
    assert all(state.status == Status.EMPTY for state in engine.decks)


@pytest.mark.parametrize("elapsed", [-1, float("nan"), float("inf")])
def test_invalid_elapsed_time_is_rejected(elapsed):
    with pytest.raises(ValueError):
        DemoEngine().advance(elapsed)
