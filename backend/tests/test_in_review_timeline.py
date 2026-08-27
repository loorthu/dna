"""Attributing a sentence to the shot that was on screen when it was SPOKEN.

The numbers here are from the meeting that exposed the bug (playlist 462598, 2026-08-27). Each
shot's version number was read aloud, then In Review was clicked for the next one. Vexa confirmed
each segment five to seven seconds later, and reading the mark at arrival filed two of the three
shots' identifiers under the following shot: "Scout 42" belonged to the first shot and landed on
the second, "Scout 45." belonged to the second and landed on the third.
"""

from datetime import datetime, timezone

from dna.in_review_timeline import (
    append_to_history,
    parse_utc,
    version_in_review_at,
)

SHOT_1, SHOT_2, SHOT_3 = 5720411, 5722946, 5723179

# The real clicks, as recorded offsets into the meeting: 21.58s, 47.51s, 63.25s.
REAL_HISTORY = [
    {"version_id": SHOT_1, "since": "2026-08-27T21:17:37.379Z"},
    {"version_id": SHOT_2, "since": "2026-08-27T21:18:03.308Z"},
    {"version_id": SHOT_3, "since": "2026-08-27T21:18:19.046Z"},
]


class TestTheMeetingThatExposedIt:
    def test_scout_42_belongs_to_the_shot_it_was_read_for(self):
        """Spoken at 39.40s, confirmed after the click at 47.51s. The words came first."""
        assert version_in_review_at(REAL_HISTORY, "2026-08-27T21:17:55.200Z") == SHOT_1

    def test_scout_45_belongs_to_the_shot_it_was_read_for(self):
        """Spoken at 56.55s, confirmed after the click at 63.25s."""
        assert version_in_review_at(REAL_HISTORY, "2026-08-27T21:18:12.350Z") == SHOT_2

    def test_every_segment_of_that_meeting_lands_where_it_was_said(self):
        spoken_and_expected = [
            ("2026-08-27T21:17:42.400Z", SHOT_1),  # 26.60s "Let us see."
            ("2026-08-27T21:17:45.470Z", SHOT_1),  # 29.67s "if this is working"
            ("2026-08-27T21:17:49.050Z", SHOT_1),  # 33.25s "version number ... 1777"
            (
                "2026-08-27T21:17:55.200Z",
                SHOT_1,
            ),  # 39.40s "Scout 42"      <- was SHOT_2
            ("2026-08-27T21:18:05.430Z", SHOT_2),  # 49.63s "next one is"
            ("2026-08-27T21:18:08.260Z", SHOT_2),  # 52.46s "One, seven, eight, eight."
            (
                "2026-08-27T21:18:12.350Z",
                SHOT_2,
            ),  # 56.55s "Scout 45."     <- was SHOT_3
            ("2026-08-27T21:18:20.800Z", SHOT_3),  # 65.00s "The last one is"
            ("2026-08-27T21:18:23.610Z", SHOT_3),  # 67.81s "One seven nine four ..."
        ]
        assert [
            version_in_review_at(REAL_HISTORY, spoken)
            for spoken, _ in spoken_and_expected
        ] == [expected for _, expected in spoken_and_expected]

    def test_speech_before_the_first_click_belongs_to_nothing(self):
        """Not the fallback. Someone talking before any shot is marked is the discard case, and
        filing it under whichever shot was eventually chosen invents an attribution."""
        assert (
            version_in_review_at(
                REAL_HISTORY, "2026-08-27T21:17:19.400Z", fallback=SHOT_3
            )
            is None
        )


class TestWhatItFallsBackTo:
    def test_no_history_means_the_current_mark(self):
        """Every playlist recorded before the timeline existed. Their behaviour is unchanged."""
        assert version_in_review_at([], "2026-08-27T21:17:55.200Z", SHOT_2) == SHOT_2
        assert version_in_review_at(None, "2026-08-27T21:17:55.200Z", SHOT_2) == SHOT_2

    def test_an_unreadable_segment_time_means_the_current_mark(self):
        assert version_in_review_at(REAL_HISTORY, "not a time", SHOT_3) == SHOT_3
        assert version_in_review_at(REAL_HISTORY, None, SHOT_3) == SHOT_3

    def test_entries_with_no_usable_time_are_skipped_not_trusted(self):
        history = [
            {"version_id": SHOT_1, "since": "2026-08-27T21:17:37.379Z"},
            {"version_id": 999, "since": "nonsense"},
        ]
        assert (
            version_in_review_at(history, "2026-08-27T21:18:30Z", fallback=None)
            == SHOT_1
        )

    def test_a_history_of_nothing_usable_means_the_current_mark(self):
        history = [{"version_id": 999, "since": "nonsense"}]
        assert version_in_review_at(history, "2026-08-27T21:18:30Z", SHOT_2) == SHOT_2


class TestClearingTheMark:
    def test_a_cleared_mark_is_an_entry_not_an_absence(self):
        """The meeting ends and the mark is unset. Words after that belong to no version — the
        timeline has to say so, or the last shot would keep collecting them."""
        history = REAL_HISTORY + [
            {"version_id": None, "since": "2026-08-27T21:18:33.437Z"}
        ]

        assert version_in_review_at(history, "2026-08-27T21:18:23.610Z") == SHOT_3
        assert version_in_review_at(history, "2026-08-27T21:18:40.000Z") is None


class TestAppending:
    def test_a_change_is_recorded_with_the_moment_it_happened(self):
        at = datetime(2026, 8, 27, 21, 18, 3, 308000, tzinfo=timezone.utc)

        history = append_to_history([], SHOT_1, at)

        assert history == [
            {"version_id": SHOT_1, "since": "2026-08-27T21:18:03.308000Z"}
        ]

    def test_remarking_the_same_version_is_not_a_boundary(self):
        """Clicking In Review on the shot already in review must not move the boundary: words
        spoken before the re-click would land on the far side of a boundary that did not move.
        """
        first = datetime(2026, 8, 27, 21, 17, 37, tzinfo=timezone.utc)
        later = datetime(2026, 8, 27, 21, 18, 50, tzinfo=timezone.utc)

        history = append_to_history([], SHOT_1, first)
        assert append_to_history(history, SHOT_1, later) == history

    def test_clearing_after_a_clear_is_not_a_boundary_either(self):
        at = datetime(2026, 8, 27, 21, 18, 33, tzinfo=timezone.utc)
        history = append_to_history([{"version_id": None, "since": "x"}], None, at)
        assert len(history) == 1

    def test_out_of_order_entries_are_ordered_before_being_read(self):
        """The answer depends on the order, so it is sorted rather than assumed — an append that
        arrived late would otherwise misfile silently."""
        scrambled = [REAL_HISTORY[2], REAL_HISTORY[0], REAL_HISTORY[1]]
        assert version_in_review_at(scrambled, "2026-08-27T21:17:55.200Z") == SHOT_1


class TestParsing:
    def test_naive_times_are_read_as_utc(self):
        """Both sides are produced by this deployment. Guessing a local zone would shift every
        boundary by hours, which reads as a plausible attribution rather than an error.
        """
        assert parse_utc("2026-08-27T21:17:37.379") == datetime(
            2026, 8, 27, 21, 17, 37, 379000, tzinfo=timezone.utc
        )

    def test_datetimes_pass_through(self):
        aware = datetime(2026, 8, 27, tzinfo=timezone.utc)
        assert parse_utc(aware) == aware

    def test_junk_is_none_rather_than_a_guess(self):
        for junk in ("", "yesterday", None, 42, []):
            assert parse_utc(junk) is None
