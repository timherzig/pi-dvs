"""Shared request pacing, fair catalog access and cancelled waiter cleanup."""

import time
from threading import Barrier, Event, Thread

import pytest

from pi_dvs.link.media import Cancel
from pi_dvs.link.scheduling import Requests
from pi_dvs.rekordbox.records import ImportCancelled


@pytest.mark.parametrize("progressive, minimum_gap", [(False, 0.0038), (True, 0.015)])
def test_catalogs_share_one_paced_wire_without_consuming_audio_budget(progressive, minimum_gap):
    requests = Requests()
    barrier = Barrier(3)
    active = 0
    observed = []
    failures = []

    def work(catalog):
        nonlocal active
        try:
            barrier.wait(2)
            for _ in range(12):
                with requests.turn(lambda: None, 0.002, catalog=catalog):
                    active += 1
                    assert active == 1
                    observed.append((catalog, time.monotonic()))
                    time.sleep(0.0002)
                    active -= 1
        except Exception as error:
            failures.append(error)

    a, b = Thread(target=work, args=(False,)), Thread(target=work, args=(True,))
    with requests.audio(progressive=progressive):
        a.start()
        b.start()
        barrier.wait(2)
        a.join(3)
        b.join(3)
    assert not a.is_alive() and not b.is_alive() and not failures
    assert len(observed) == 24
    assert all(y[1] - x[1] >= 0.0018 for x, y in zip(observed, observed[1:], strict=False))
    catalogs = [at for catalog, at in observed if catalog]
    assert all(y - x >= minimum_gap for x, y in zip(catalogs, catalogs[1:], strict=False))
    # Metadata made progress before the audio sequence ended.
    assert sum(catalog for catalog, _ in observed[:12]) >= (1 if progressive else 4)


def test_cancelled_waiter_does_not_block_following_requests():
    requests = Requests()
    cancel, waiting, finished = Event(), Event(), Event()

    def waiter():
        waiting.set()
        with pytest.raises(ImportCancelled):
            with requests.turn(Cancel(cancel).check, 0, catalog=True):
                pytest.fail("Cancelled work started")
        finished.set()

    with requests.turn(lambda: None, 0, catalog=False):
        thread = Thread(target=waiter)
        thread.start()
        assert waiting.wait(1)
        cancel.set()
        assert finished.wait(1)
    thread.join(1)
    with requests.turn(lambda: None, 0, catalog=True):
        pass


def test_failed_request_releases_wire_and_audio_scope():
    requests = Requests()
    with pytest.raises(ValueError), requests.audio():
        with requests.turn(lambda: None, 0, catalog=False):
            raise ValueError("injected network failure")
    with requests.turn(lambda: None, 0, catalog=True):
        pass


def test_paused_sender_still_paces_the_following_wire_request():
    requests = Requests()
    with requests.turn(lambda: None, 0.02, catalog=False):
        time.sleep(0.03)  # A descheduled sender misses the original reservation.
        requests.sent(0.02, catalog=False)
        sent_at = time.monotonic()
    with requests.turn(lambda: None, 0.02, catalog=False):
        assert time.monotonic() - sent_at >= 0.019


def test_full_file_sharing_does_not_idle_between_eligible_requests(monkeypatch):
    requests = Requests()
    now = 0.0
    waits = []

    def wait(timeout):
        nonlocal now
        waits.append(timeout)
        now += timeout

    monkeypatch.setattr("pi_dvs.link.scheduling.time.monotonic", lambda: now)
    monkeypatch.setattr(requests._condition, "wait", wait)
    with requests.audio():
        with requests.turn(lambda: None, 0.005, catalog=True):
            requests.sent(0.005, catalog=True)
        # The wire is free but this catalog's quota expires after the wire pace.
        # No worker notification will arrive: both deadlines must wake us.
        with requests.turn(lambda: None, 0.005, catalog=True):
            assert now == pytest.approx(0.010)
    assert waits == pytest.approx([0.005, 0.005])
