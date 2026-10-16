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
    engine.set_needle(0, True)
    engine.set_platter(0, True)
    engine.advance(2)
    assert engine.decks[0].position == 2
    engine.load(1, Track("two", "Two", "Artist", 20))
    engine.advance(0.5)
    assert engine.decks[0].position == 2.5
    assert engine.decks[1].status == Status.READY
    assert engine.decks[1].position == 0


def test_playback_requires_both_needle_and_motion_and_holds_position(track):
    engine = DemoEngine()
    engine.load(0, track)
    engine.advance(1)
    engine.set_platter(0, True)
    engine.advance(2)
    assert engine.decks[0].status == Status.READY
    assert engine.decks[0].position == 0
    engine.set_needle(0, True)
    engine.advance(4)
    engine.set_platter(0, False)
    engine.advance(100)
    assert engine.decks[0].status == Status.STOPPED
    assert engine.decks[0].position == 4
    engine.set_platter(0, True)
    engine.advance(1)
    engine.set_needle(0, False)
    engine.advance(100)
    assert engine.decks[0].status == Status.READY
    assert engine.decks[0].position == 5
    engine.set_needle(0, True)
    engine.advance(1)
    assert engine.decks[0].status == Status.PLAYING
    assert engine.decks[0].position == 6


def test_finished_track_does_not_restart_when_vinyl_controls_change(track):
    engine = DemoEngine()
    engine.load(0, track)
    engine.advance(1)
    engine.set_needle(0, True)
    engine.set_platter(0, True)
    engine.advance(100)
    assert engine.decks[0].position == track.duration
    assert engine.decks[0].status == Status.FINISHED
    engine.set_needle(0, False)
    engine.set_platter(0, False)
    engine.set_needle(0, True)
    engine.set_platter(0, True)
    engine.advance(100)
    assert engine.decks[0].position == track.duration
    assert engine.decks[0].status == Status.FINISHED
    engine.set_platter(0, False)
    engine.load(0, track)
    engine.advance(1)
    assert engine.decks[0].position == 0
    assert engine.decks[0].status == Status.STOPPED


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


def test_load_completion_follows_current_vinyl_without_counting_loading_time(track):
    engine = DemoEngine()
    engine.set_needle(0, True)
    engine.load(0, track)
    engine.advance(0.1)
    engine.set_platter(0, True)
    assert engine.decks[0].status == Status.LOADING
    engine.advance(0.5)
    assert engine.decks[0].status == Status.PLAYING
    assert engine.decks[0].position == pytest.approx(0.25)


def test_lifted_needle_allows_changes_on_a_spinning_platter(track):
    engine = DemoEngine()
    engine.set_platter(0, True)
    engine.load(0, track)
    engine.advance(1)
    assert engine.decks[0].status == Status.READY
    assert engine.decks[0].platter_spinning
    engine.unload(0)
    assert engine.decks[0].status == Status.EMPTY
    assert engine.decks[0].platter_spinning
    engine.advance(1)
    assert engine.decks[0].position == 0


def test_failed_load_can_be_recovered_and_has_no_transport(track):
    engine = DemoEngine()
    engine.load(0, Track("missing", "Missing", "Artist", 10, available=False))
    engine.set_needle(0, True)
    engine.set_platter(0, True)
    assert engine.decks[0].status == Status.LOADING
    engine.advance(1)
    assert engine.decks[0].status == Status.ERROR
    assert engine.decks[0].error
    assert engine.decks[0].position == 0
    engine.set_platter(0, False)
    assert engine.decks[0].status == Status.ERROR
    engine.load(0, track)
    engine.advance(1)
    assert engine.decks[0].status == Status.STOPPED
    assert engine.decks[0].error == ""
    engine.set_platter(0, True)
    assert engine.decks[0].status == Status.PLAYING


@pytest.mark.parametrize("condition", ["empty", "loading", "playing", "error", "finished"])
def test_moving_vinyl_blocks_track_changes_even_without_playback(condition, track):
    engine = DemoEngine()
    if condition != "empty":
        candidate = Track("missing", "Missing", "Artist", 10, available=False)
        engine.load(0, candidate if condition == "error" else track)
        if condition != "loading":
            engine.advance(1)
    engine.set_needle(0, True)
    engine.set_platter(0, True)
    if condition == "finished":
        engine.advance(100)
    before = engine.decks
    assert not before[0].can_change_track
    with pytest.raises(ValueError, match="Stop the record"):
        engine.load(0, Track("two", "Two", "Artist", 20))
    with pytest.raises(ValueError, match="Stop the record"):
        engine.unload(0)
    assert engine.decks == before
    # Stopping is enough, even with the needle down. The controls survive track changes.
    engine.set_platter(0, False)
    assert engine.decks[0].can_change_track
    engine.load(0, track)
    engine.advance(1)
    assert engine.decks[0].status == Status.STOPPED
    assert engine.decks[0].needle_down
    engine.unload(0)
    assert engine.decks[0].track is None
    assert engine.decks[0].needle_down


@pytest.mark.parametrize("deck", [-1, 2])
def test_invalid_deck_cannot_modify_another_deck(deck, track):
    engine = DemoEngine()
    for action in (
        lambda: engine.load(deck, track),
        lambda: engine.unload(deck),
        lambda: engine.set_needle(deck, True),
        lambda: engine.set_platter(deck, True),
    ):
        with pytest.raises(ValueError):
            action()
    assert all(state.status == Status.EMPTY for state in engine.decks)


@pytest.mark.parametrize("elapsed", [-1, float("nan"), float("inf")])
def test_invalid_elapsed_time_is_rejected(elapsed):
    with pytest.raises(ValueError):
        DemoEngine().advance(elapsed)
