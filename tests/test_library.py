from pathlib import Path

import pytest

from pi_dvs.library import Library, demo_library
from pi_dvs.model import Track
from pi_dvs.presentation import artwork_url


def test_search_is_case_accent_and_whitespace_insensitive():
    library = demo_library()
    assert [track.id for track in library.search("  CAFE  éLaN ")] == ["cafe"]
    assert [track.id for track in library.search("soft circuit")] == ["after-hours", "return"]
    assert library.search("   ") == library.tracks
    assert library.search("no such artist") == ()


def test_filtering_does_not_change_track_identity_or_catalog():
    library = demo_library()
    track = library.search("blue")[0]
    assert library.get(track.id) is track
    assert len(library.tracks) == 8


def test_duplicate_ids_are_rejected():
    track = Track("same", "Title", "Artist", 10)
    with pytest.raises(ValueError, match="unique"):
        Library((track, track))


def test_artwork_missing_or_absent_has_a_fallback(tmp_path):
    assert artwork_url(None) == ""
    assert artwork_url(Track("one", "Title", "Artist", 10)) == ""
    assert artwork_url(Track("one", "Title", "Artist", 10, tmp_path / "gone.svg")) == ""
    path = tmp_path / "cover with spaces.svg"
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    assert artwork_url(Track("one", "Title", "Artist", 10, path)) == path.as_uri()


def test_bundled_artwork_exists_and_demo_has_recovery_examples():
    tracks = demo_library().tracks
    assert all(
        isinstance(track.artwork, Path) and track.artwork.is_file()
        for track in tracks
        if track.artwork
    )
    assert any(track.artwork is None for track in tracks)
    assert any(not track.available for track in tracks)
