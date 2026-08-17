"""
Regression coverage for Finding 5 / Slice F: filtered-music row identity.

Builds a fixture library where filtering reorders/subsets the visible rows,
then proves that selecting visible filtered row 0 resolves to that exact
track — not whatever happens to sit at row 0 of the unfiltered master list.
"""
from core.music import Track
from ui.main_window import MusicTab


def _make_fixture_tracks():
    """
    Five tracks. Searching for 'Zephyr' matches only the last one
    (master-list index 4), so after filtering, displayed row 0 must resolve
    to the Zephyr track — not master row 0 (Alpha).
    """
    return [
        Track(path="/mnt/Alpha.mp3", filename="Alpha.mp3", title="Alpha", artist="Band A", tags_loaded=True),
        Track(path="/mnt/Bravo.mp3", filename="Bravo.mp3", title="Bravo", artist="Band B", tags_loaded=True),
        Track(path="/mnt/Charlie.mp3", filename="Charlie.mp3", title="Charlie", artist="Band C", tags_loaded=True),
        Track(path="/mnt/Delta.mp3", filename="Delta.mp3", title="Delta", artist="Band D", tags_loaded=True),
        Track(path="/mnt/Zephyr.mp3", filename="Zephyr.mp3", title="Zephyr", artist="Band Z", tags_loaded=True),
    ]


def _load_fixture(tab, tracks):
    """
    Populate a MusicTab as if a scan had just completed, bypassing the
    real background scanner thread. filter_tracks() reads from the
    scanner's own internal list, so that must be seeded too (same Track
    objects, so path-identity lookups line up correctly).
    """
    tab._scanner._tracks = tracks
    tab._populate_table(tracks)


def test_filtering_does_not_reorder_master_list(qapp):
    tab = MusicTab()
    tracks = _make_fixture_tracks()
    _load_fixture(tab, tracks)

    tab._filter_tracks("zephyr")

    # Sanity check that this fixture actually exercises the bug: the
    # filtered track at visible row 0 must NOT be the same object as
    # master-list row 0 (Alpha). If it were, this test wouldn't be
    # distinguishing the old (broken) addressing from the new one.
    assert tab._all_tracks[0].title == "Alpha"
    assert tab._track_at_row(0).title == "Zephyr"
    assert tab._track_at_row(0) is not tab._all_tracks[0]


def test_track_at_row_resolves_visible_filtered_row_not_master_row(qapp):
    """
    This is the direct regression test: it must fail against the old
    implementation, where every row-based action indexed self._tracks
    (== self._all_tracks here) with the visible table row number.
    """
    tab = MusicTab()
    tracks = _make_fixture_tracks()
    _load_fixture(tab, tracks)

    tab._filter_tracks("zephyr")

    resolved = tab._track_at_row(0)
    assert resolved is not None
    assert resolved.path == "/mnt/Zephyr.mp3"
    assert resolved.title == "Zephyr"

    # The old buggy equivalent of this action was `self._tracks[0]` —
    # explicitly prove that differs from the correct answer for this fixture.
    old_buggy_result = tab._all_tracks[0]
    assert old_buggy_result is not resolved
    assert old_buggy_result.title == "Alpha"


def test_double_click_playlist_matches_displayed_tracks_after_filter(qapp):
    """
    _on_double_click must build the player's playlist from the displayed
    (filtered) set, with the clicked row as the start index into that same
    set — not the unfiltered master list.
    """
    tab = MusicTab()
    tracks = _make_fixture_tracks()
    _load_fixture(tab, tracks)
    tab._filter_tracks("zephyr")

    captured = {}

    class _FakePlayer:
        def set_playlist(self, playlist, start_index):
            captured["playlist"] = playlist
            captured["start_index"] = start_index

    tab.set_player(_FakePlayer())

    class _FakeIndex:
        def row(self):
            return 0

    tab._on_double_click(_FakeIndex())

    assert captured["playlist"] == tab._displayed_tracks
    assert captured["playlist"][captured["start_index"]].title == "Zephyr"


def test_filter_then_clear_restores_full_displayed_list(qapp):
    tab = MusicTab()
    tracks = _make_fixture_tracks()
    _load_fixture(tab, tracks)

    tab._filter_tracks("zephyr")
    assert len(tab._displayed_tracks) == 1

    tab._filter_tracks("")  # clear the search box
    assert len(tab._displayed_tracks) == 5
    assert tab._track_at_row(0).title == "Alpha"


def test_hydration_update_targets_correct_row_while_filtered(qapp):
    """
    _refresh_rows(indices) receives positions into _all_tracks (scanner
    order), not table rows. While a filter is active, hydration for a track
    that's currently visible must update that track's actual displayed row
    — not whatever row shares the same numeric index in the master list.
    """
    tab = MusicTab()
    tracks = _make_fixture_tracks()
    _load_fixture(tab, tracks)

    # Filter down to just Charlie (master index 2) and Zephyr (master index 4).
    tab._filter_tracks("")
    tab._fill_table([tracks[2], tracks[4]])  # Charlie at displayed row 0, Zephyr at row 1
    assert tab._track_at_row(0).title == "Charlie"

    # Simulate Phase 2 hydration completing for Zephyr (master index 4) with
    # a new title — this must land on displayed row 1 (Zephyr), not row 4
    # (out of range) or row 0 (Charlie).
    tracks[4].title = "Zephyr (Remastered)"
    tab._refresh_rows([4])

    assert tab.table.item(1, 1).text() == "Zephyr (Remastered)"
    assert tab.table.item(0, 1).text() == "Charlie"
