"""Tests for the pure video-segment cut-list builder and Zoom alignment helper.

Slice 1 of the movie-file-segmenting feature. These functions are pure: no
storage, no provider, no ffmpeg, no FastAPI. They replay segmentation decisions
already encoded in the stored transcript segments' wall-clock timestamps.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from dna.models.stored_segment import StoredSegment
from dna.video_segment_publish import (
    in_review_periods,
    build_video_cuts_payload,
    parse_recording_t0_from_zoom_folder,
    recording_t0_from_meeting_end,
    recording_t0_from_vexa,
    resolve_recording_t0,
)


def _segment(
    *,
    segment_id: str,
    version_id: int = 10,
    start: str,
    end: str,
    playlist_id: int = 1,
) -> StoredSegment:
    """Build a StoredSegment with the wall-clock fields the builder reads."""
    ts = datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc)
    return StoredSegment(
        _id="mongo_" + segment_id,
        segment_id=segment_id,
        playlist_id=playlist_id,
        version_id=version_id,
        text="hello",
        speaker="Speaker A",
        language="en",
        absolute_start_time=start,
        absolute_end_time=end,
        vexa_updated_at=None,
        created_at=ts,
        updated_at=ts,
    )


# Recording starts at 2026-05-27T10:00:00Z. A long-enough duration that nothing
# clamps unless a test deliberately uses out-of-range times.
T0 = datetime(2026, 5, 27, 10, 0, 0, tzinfo=timezone.utc)
DURATION = 3600.0  # one hour


class TestParseRecordingT0FromZoomFolder:
    """Folder name -> recording_t0 (UTC), via the ZOOM_RECORDING_TIMEZONE zone."""

    def test_parses_basic_folder_name_as_new_york(self, monkeypatch):
        monkeypatch.setenv("ZOOM_RECORDING_TIMEZONE", "America/New_York")
        folder = "2026-05-27 06.44.49 Cameron Target's Zoom Meeting"

        t0 = parse_recording_t0_from_zoom_folder(folder)

        # 2026-05-27 is EDT (UTC-4): 06:44:49 local -> 10:44:49 UTC.
        assert t0 == datetime(2026, 5, 27, 10, 44, 49, tzinfo=timezone.utc)
        assert t0.tzinfo == timezone.utc

    def test_winter_date_uses_est_offset(self, monkeypatch):
        monkeypatch.setenv("ZOOM_RECORDING_TIMEZONE", "America/New_York")
        # 2026-01-15 is EST (UTC-5): 06:00:00 local -> 11:00:00 UTC.
        t0 = parse_recording_t0_from_zoom_folder("2026-01-15 06.00.00 Meeting")

        assert t0 == datetime(2026, 1, 15, 11, 0, 0, tzinfo=timezone.utc)

    def test_default_timezone_is_new_york_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("ZOOM_RECORDING_TIMEZONE", raising=False)
        t0 = parse_recording_t0_from_zoom_folder("2026-05-27 06.44.49 Meeting")

        assert t0 == datetime(2026, 5, 27, 10, 44, 49, tzinfo=timezone.utc)

    def test_respects_overridden_timezone(self, monkeypatch):
        monkeypatch.setenv("ZOOM_RECORDING_TIMEZONE", "UTC")
        t0 = parse_recording_t0_from_zoom_folder("2026-05-27 06.44.49 Meeting")

        assert t0 == datetime(2026, 5, 27, 6, 44, 49, tzinfo=timezone.utc)

    def test_folder_name_without_title_still_parses(self, monkeypatch):
        monkeypatch.setenv("ZOOM_RECORDING_TIMEZONE", "UTC")
        t0 = parse_recording_t0_from_zoom_folder("2026-05-27 06.44.49")

        assert t0 == datetime(2026, 5, 27, 6, 44, 49, tzinfo=timezone.utc)

    def test_leading_and_trailing_whitespace_tolerated(self, monkeypatch):
        monkeypatch.setenv("ZOOM_RECORDING_TIMEZONE", "UTC")
        t0 = parse_recording_t0_from_zoom_folder("  2026-05-27 06.44.49 Meeting  ")

        assert t0 == datetime(2026, 5, 27, 6, 44, 49, tzinfo=timezone.utc)

    def test_unparseable_folder_name_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_recording_t0_from_zoom_folder("not a zoom folder")

    def test_empty_folder_name_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_recording_t0_from_zoom_folder("")


class TestRecordingT0FromMeetingEnd:
    """t0 derived by working backward from the bot-leave (meeting end) time."""

    def test_subtracts_duration_from_end(self):
        ended = datetime(2026, 5, 27, 11, 0, 0, tzinfo=timezone.utc)
        t0 = recording_t0_from_meeting_end(ended, 3600.0)
        assert t0 == datetime(2026, 5, 27, 10, 0, 0, tzinfo=timezone.utc)

    def test_positive_offset_shifts_t0_later(self):
        ended = datetime(2026, 5, 27, 11, 0, 0, tzinfo=timezone.utc)
        t0 = recording_t0_from_meeting_end(ended, 3600.0, offset_seconds=5.0)
        assert t0 == datetime(2026, 5, 27, 10, 0, 5, tzinfo=timezone.utc)

    def test_negative_offset_shifts_t0_earlier(self):
        ended = datetime(2026, 5, 27, 11, 0, 0, tzinfo=timezone.utc)
        t0 = recording_t0_from_meeting_end(ended, 3600.0, offset_seconds=-10.0)
        assert t0 == datetime(2026, 5, 27, 9, 59, 50, tzinfo=timezone.utc)

    def test_naive_end_treated_as_utc(self):
        ended = datetime(2026, 5, 27, 11, 0, 0)  # naive
        t0 = recording_t0_from_meeting_end(ended, 600.0)
        assert t0 == datetime(2026, 5, 27, 10, 50, 0, tzinfo=timezone.utc)
        assert t0.tzinfo == timezone.utc

    def test_non_utc_end_converted(self):
        ended = datetime(
            2026, 5, 27, 7, 0, 0, tzinfo=ZoneInfo("America/New_York")
        )  # 11:00 UTC (EDT)
        t0 = recording_t0_from_meeting_end(ended, 3600.0)
        assert t0 == datetime(2026, 5, 27, 10, 0, 0, tzinfo=timezone.utc)


def _mark(version_id, at: str) -> dict:
    """One entry in the in-review timeline: the mark moving to ``version_id`` at ``at``."""
    return {"version_id": version_id, "since": at}


class TestBuildVideoCutsPayload:
    """A cut is one period the operator held a shot under review.

    Not a run of uninterrupted speech. The rule this replaced started a new cut wherever a pause
    exceeded two seconds, which on a real meeting gave the first shot three clips, the second two
    and the third one while the operator did the same thing each time — the pauses measured 2.54s,
    2.31s, 2.04s, 1.53s and 0.78s, so a breath decided the answer. Marking a shot is the operator
    saying what is being discussed, and that stays true through every pause in the room.
    """

    def test_empty_input_returns_empty_list(self):
        result = build_video_cuts_payload(
            {}, recording_t0=T0, recording_duration_seconds=DURATION
        )

        assert result == []

    def test_no_timeline_yields_no_cuts(self):
        """Guessing boundaries from speech rhythm is worse than not answering."""
        segments = {
            10: [
                _segment(
                    segment_id="a",
                    start="2026-05-27T10:05:00Z",
                    end="2026-05-27T10:05:10Z",
                )
            ]
        }

        result = build_video_cuts_payload(
            segments, recording_t0=T0, recording_duration_seconds=DURATION
        )

        assert result[0].cuts == []

    def test_one_period_is_one_cut_however_many_pauses_it_contains(self):
        """Two utterances a full minute apart, one period: one clip covering the period."""
        segments = {
            10: [
                _segment(
                    segment_id="a",
                    start="2026-05-27T10:05:00Z",
                    end="2026-05-27T10:05:10Z",
                ),
                _segment(
                    segment_id="b",
                    start="2026-05-27T10:06:10Z",
                    end="2026-05-27T10:06:20Z",
                ),
            ]
        }

        result = build_video_cuts_payload(
            segments,
            recording_t0=T0,
            recording_duration_seconds=DURATION,
            in_review_history=[
                _mark(10, "2026-05-27T10:04:30Z"),
                _mark(None, "2026-05-27T10:07:00Z"),
            ],
        )

        assert len(result) == 1
        cut_list = result[0]
        assert cut_list.version_id == 10
        assert len(cut_list.cuts) == 1
        cut = cut_list.cuts[0]
        # The period, 270s..420s — not 300s..380s, which is where the talking happened.
        assert cut.video_in_seconds == 270.0
        assert cut.video_out_seconds == 420.0
        assert cut.transcript_segment_ids == ["a", "b"]

    def test_returning_to_a_version_is_a_second_cut(self):
        """The only split that means anything: the operator marked it again."""
        segments = {
            10: [
                _segment(
                    segment_id="a",
                    start="2026-05-27T10:05:00Z",
                    end="2026-05-27T10:05:10Z",
                ),
                _segment(
                    segment_id="b",
                    start="2026-05-27T10:20:00Z",
                    end="2026-05-27T10:20:10Z",
                ),
            ]
        }

        result = build_video_cuts_payload(
            segments,
            recording_t0=T0,
            recording_duration_seconds=DURATION,
            in_review_history=[
                _mark(10, "2026-05-27T10:04:00Z"),
                _mark(20, "2026-05-27T10:10:00Z"),
                _mark(10, "2026-05-27T10:19:00Z"),
                _mark(None, "2026-05-27T10:21:00Z"),
            ],
        )

        cuts = result[0].cuts
        assert len(cuts) == 2
        assert (cuts[0].video_in_seconds, cuts[0].video_out_seconds) == (240.0, 600.0)
        assert (cuts[1].video_in_seconds, cuts[1].video_out_seconds) == (1140.0, 1260.0)
        assert cuts[0].transcript_segment_ids == ["a"]
        assert cuts[1].transcript_segment_ids == ["b"]

    def test_a_period_where_nobody_spoke_is_dropped(self):
        """A shot on screen in silence has no discussion to play back."""
        segments = {
            10: [
                _segment(
                    segment_id="a",
                    start="2026-05-27T10:05:00Z",
                    end="2026-05-27T10:05:10Z",
                )
            ]
        }

        result = build_video_cuts_payload(
            segments,
            recording_t0=T0,
            recording_duration_seconds=DURATION,
            in_review_history=[
                _mark(10, "2026-05-27T10:04:00Z"),
                _mark(20, "2026-05-27T10:06:00Z"),
                _mark(10, "2026-05-27T10:30:00Z"),  # marked again, nothing said
                _mark(None, "2026-05-27T10:32:00Z"),
            ],
        )

        assert len(result[0].cuts) == 1

    def test_multi_version_grouped_and_ordered_by_version_id(self):
        segments = {
            20: [
                _segment(
                    segment_id="x",
                    version_id=20,
                    start="2026-05-27T10:10:05Z",
                    end="2026-05-27T10:10:08Z",
                )
            ],
            10: [
                _segment(
                    segment_id="y",
                    start="2026-05-27T10:11:05Z",
                    end="2026-05-27T10:11:08Z",
                )
            ],
        }

        result = build_video_cuts_payload(
            segments,
            recording_t0=T0,
            recording_duration_seconds=DURATION,
            in_review_history=[
                _mark(20, "2026-05-27T10:10:00Z"),
                _mark(10, "2026-05-27T10:11:00Z"),
                _mark(None, "2026-05-27T10:12:00Z"),
            ],
        )

        assert [cl.version_id for cl in result] == [10, 20]

    def test_segment_ids_are_ordered_by_when_they_were_spoken(self):
        """Given out of order; the clip lists them in the order the room heard them."""
        segments = {
            10: [
                _segment(
                    segment_id="b",
                    start="2026-05-27T10:05:11Z",
                    end="2026-05-27T10:05:30Z",
                ),
                _segment(
                    segment_id="a",
                    start="2026-05-27T10:05:00Z",
                    end="2026-05-27T10:05:10Z",
                ),
            ]
        }

        result = build_video_cuts_payload(
            segments,
            recording_t0=T0,
            recording_duration_seconds=DURATION,
            in_review_history=[
                _mark(10, "2026-05-27T10:04:00Z"),
                _mark(None, "2026-05-27T10:06:00Z"),
            ],
        )

        assert result[0].cuts[0].transcript_segment_ids == ["a", "b"]

    def test_period_entirely_before_the_recording_is_dropped(self):
        segments = {
            10: [
                _segment(
                    segment_id="a",
                    start="2026-05-27T09:00:05Z",
                    end="2026-05-27T09:00:08Z",
                )
            ]
        }

        result = build_video_cuts_payload(
            segments,
            recording_t0=T0,
            recording_duration_seconds=DURATION,
            in_review_history=[
                _mark(10, "2026-05-27T09:00:00Z"),
                _mark(None, "2026-05-27T09:00:10Z"),
            ],
        )

        assert result[0].cuts == []

    def test_period_entirely_after_the_recording_is_dropped(self):
        segments = {
            10: [
                _segment(
                    segment_id="a",
                    start="2026-05-27T11:30:05Z",
                    end="2026-05-27T11:30:08Z",
                )
            ]
        }

        result = build_video_cuts_payload(
            segments,
            recording_t0=T0,
            recording_duration_seconds=DURATION,
            in_review_history=[
                _mark(10, "2026-05-27T11:30:00Z"),
                _mark(None, "2026-05-27T11:30:10Z"),
            ],
        )

        assert result[0].cuts == []

    def test_a_period_that_began_before_the_recording_is_clamped_to_zero(self):
        """The shot was already under review when the bot started recording."""
        segments = {
            10: [
                _segment(
                    segment_id="a",
                    start="2026-05-27T10:00:05Z",
                    end="2026-05-27T10:00:10Z",
                )
            ]
        }

        result = build_video_cuts_payload(
            segments,
            recording_t0=T0,
            recording_duration_seconds=DURATION,
            in_review_history=[
                _mark(10, "2026-05-27T09:59:30Z"),
                _mark(None, "2026-05-27T10:00:30Z"),
            ],
        )

        cut = result[0].cuts[0]
        assert cut.video_in_seconds == 0.0
        assert cut.video_out_seconds == 30.0

    def test_a_period_outliving_the_recording_is_clamped_to_the_media(self):
        """The bot stops recording before the operator moves on."""
        segments = {
            10: [
                _segment(
                    segment_id="a",
                    start="2026-05-27T10:01:35Z",
                    end="2026-05-27T10:01:40Z",
                )
            ]
        }

        result = build_video_cuts_payload(
            segments,
            recording_t0=T0,
            recording_duration_seconds=100.0,
            in_review_history=[
                _mark(10, "2026-05-27T10:01:30Z"),
                _mark(None, "2026-05-27T10:02:10Z"),
            ],
        )

        cut = result[0].cuts[0]
        assert cut.video_in_seconds == 90.0
        assert cut.video_out_seconds == 100.0

    def test_a_zero_length_period_is_dropped(self):
        """Two marks at the same instant — a mis-click — is not a clip."""
        segments = {
            10: [
                _segment(
                    segment_id="a",
                    start="2026-05-27T10:05:00Z",
                    end="2026-05-27T10:05:10Z",
                )
            ]
        }

        result = build_video_cuts_payload(
            segments,
            recording_t0=T0,
            recording_duration_seconds=DURATION,
            in_review_history=[
                _mark(10, "2026-05-27T10:05:00Z"),
                _mark(None, "2026-05-27T10:05:00Z"),
            ],
        )

        assert result[0].cuts == []

    def _one_period(self, segments, **over):
        kwargs = dict(
            recording_t0=T0,
            recording_duration_seconds=DURATION,
            in_review_history=[
                _mark(10, "2026-05-27T10:04:00Z"),
                _mark(None, "2026-05-27T10:07:00Z"),
            ],
        )
        kwargs.update(over)
        return build_video_cuts_payload(segments, **kwargs)

    def test_body_hash_is_stable_across_rebuilds(self):
        segments = {
            10: [
                _segment(
                    segment_id="a",
                    start="2026-05-27T10:05:00Z",
                    end="2026-05-27T10:05:10Z",
                )
            ]
        }

        first = self._one_period(segments)
        second = self._one_period(segments)

        assert first[0].body_hash == second[0].body_hash
        assert first[0].body_hash  # non-empty

    def test_body_hash_changes_when_the_cut_moves(self):
        segments = {
            10: [
                _segment(
                    segment_id="a",
                    start="2026-05-27T10:05:00Z",
                    end="2026-05-27T10:05:10Z",
                )
            ]
        }

        h1 = self._one_period(segments)[0].body_hash
        h2 = self._one_period(
            segments,
            in_review_history=[
                _mark(10, "2026-05-27T10:04:00Z"),
                _mark(None, "2026-05-27T10:08:00Z"),
            ],
        )[0].body_hash

        assert h1 != h2

    def test_version_with_only_out_of_bounds_segments_yields_empty_cuts(self):
        """Still returned, so the caller can report "nothing to publish" for it."""
        segments = {
            10: [
                _segment(
                    segment_id="a",
                    start="2026-05-27T09:00:05Z",
                    end="2026-05-27T09:00:08Z",
                )
            ]
        }

        result = build_video_cuts_payload(
            segments,
            recording_t0=T0,
            recording_duration_seconds=DURATION,
            in_review_history=[
                _mark(10, "2026-05-27T09:00:00Z"),
                _mark(None, "2026-05-27T09:00:10Z"),
            ],
        )

        assert len(result) == 1
        assert result[0].version_id == 10
        assert result[0].cuts == []

    def test_naive_absolute_timestamps_treated_as_utc(self):
        """No tz suffix must read as UTC, not host-local — a segment placed hours away would fall
        outside its period and lose its clip."""
        segments = {
            10: [
                _segment(
                    segment_id="a",
                    start="2026-05-27T10:05:00",
                    end="2026-05-27T10:05:10",
                )
            ]
        }

        result = self._one_period(segments)

        assert result[0].cuts[0].transcript_segment_ids == ["a"]


class TestInReviewPeriods:
    """Turning the mark's history into the spans each version held it."""

    ENDS = datetime(2026, 5, 27, 11, 0, 0, tzinfo=timezone.utc)

    def test_consecutive_marks_bound_each_other(self):
        periods = in_review_periods(
            [
                _mark(10, "2026-05-27T10:00:00Z"),
                _mark(20, "2026-05-27T10:10:00Z"),
            ],
            ends_at=self.ENDS,
        )

        assert [p[0] for p in periods] == [10, 20]
        assert periods[0][2] == periods[1][1]

    def test_the_last_mark_runs_to_the_end(self):
        periods = in_review_periods(
            [_mark(10, "2026-05-27T10:00:00Z")], ends_at=self.ENDS
        )

        assert periods[0][2] == self.ENDS

    def test_clearing_the_mark_ends_a_period_without_starting_one(self):
        periods = in_review_periods(
            [
                _mark(10, "2026-05-27T10:00:00Z"),
                _mark(None, "2026-05-27T10:10:00Z"),
            ],
            ends_at=self.ENDS,
        )

        assert len(periods) == 1
        assert periods[0][2] == datetime(2026, 5, 27, 10, 10, tzinfo=timezone.utc)

    def test_entries_are_ordered_before_being_paired(self):
        periods = in_review_periods(
            [
                _mark(20, "2026-05-27T10:10:00Z"),
                _mark(10, "2026-05-27T10:00:00Z"),
            ],
            ends_at=self.ENDS,
        )

        assert [p[0] for p in periods] == [10, 20]

    def test_unreadable_entries_are_skipped(self):
        periods = in_review_periods(
            [_mark(10, "2026-05-27T10:00:00Z"), _mark(20, "nonsense")],
            ends_at=self.ENDS,
        )

        assert [p[0] for p in periods] == [10]

    def test_no_history_is_no_periods(self):
        assert in_review_periods(None, ends_at=self.ENDS) == []
        assert in_review_periods([], ends_at=self.ENDS) == []


class TestRecordingT0FromVexa:
    """The recorder's own clock at its first frame — the anchor the cut list should prefer.

    Unlike the two heuristics, this is not derived from anything adjacent to the recording: the
    bot stamps it when ffmpeg starts, and it is the clock the frame pacer uses to define frame 0.
    Measured against real recordings on 2026-08-21 it is exact, where meeting-end-minus-duration
    inherits every error in the stored duration.
    """

    def test_parses_the_z_suffixed_form_vexa_actually_sends(self):
        t0 = recording_t0_from_vexa("2026-08-21T18:45:37.097Z")

        assert t0 == datetime(2026, 8, 21, 18, 45, 37, 97000, tzinfo=timezone.utc)

    def test_a_naive_timestamp_is_utc_not_host_local(self):
        """Host-local would silently shift every cut by the machine's offset."""
        t0 = recording_t0_from_vexa("2026-08-21T18:45:37")

        assert t0 == datetime(2026, 8, 21, 18, 45, 37, tzinfo=timezone.utc)

    def test_offsets_computed_against_it_match_the_measured_meeting(self):
        """The real numbers from the 2026-08-21 run, end to end.

        recording_t0 18:45:37.097; a segment spoken at 18:46:00.130 belongs 23.03s into the file.
        """
        t0 = recording_t0_from_vexa("2026-08-21T18:45:37.097Z")
        spoken_at = datetime(2026, 8, 21, 18, 46, 0, 130000, tzinfo=timezone.utc)

        assert round((spoken_at - t0).total_seconds(), 3) == 23.033


class TestResolveRecordingT0:
    """Which anchor was used has to travel with the answer.

    A cut list built on the wrong zero looks exactly like a correct one until someone plays it,
    so the source is reported rather than left to be inferred from whatever data was present.
    """

    ENDED = datetime(2026, 5, 27, 11, 0, 0, tzinfo=timezone.utc)

    def test_vexa_wins_over_every_heuristic(self):
        t0, source = resolve_recording_t0(
            vexa_start_time_utc="2026-08-21T18:45:37.097Z",
            zoom_folder_name="2026-05-27 06.44.49 Some Meeting",
            transcription_ended_at=self.ENDED,
            recording_duration_seconds=600.0,
        )

        assert source == "vexa_recorder_clock"
        assert t0 == datetime(2026, 8, 21, 18, 45, 37, 97000, tzinfo=timezone.utc)

    def test_falls_back_to_the_zoom_folder(self):
        t0, source = resolve_recording_t0(
            zoom_folder_name="2026-05-27 06.44.49 Some Meeting",
            transcription_ended_at=self.ENDED,
            recording_duration_seconds=600.0,
        )

        assert source == "zoom_folder"
        assert t0 == parse_recording_t0_from_zoom_folder(
            "2026-05-27 06.44.49 Some Meeting"
        )

    def test_an_unparseable_folder_falls_through_rather_than_failing(self):
        """A folder name that is not a Zoom stamp is not an anchor — it is not an error either."""
        t0, source = resolve_recording_t0(
            zoom_folder_name="recordings",
            transcription_ended_at=self.ENDED,
            recording_duration_seconds=600.0,
        )

        assert source == "meeting_end_minus_duration"
        assert t0 == recording_t0_from_meeting_end(self.ENDED, 600.0)

    def test_the_manual_offset_still_applies_to_the_fallback(self):
        _, source = resolve_recording_t0(
            transcription_ended_at=self.ENDED,
            recording_duration_seconds=600.0,
            offset_seconds=1.5,
        )
        t0, _ = resolve_recording_t0(
            transcription_ended_at=self.ENDED,
            recording_duration_seconds=600.0,
            offset_seconds=1.5,
        )

        assert source == "meeting_end_minus_duration"
        assert t0 == recording_t0_from_meeting_end(
            self.ENDED, 600.0, offset_seconds=1.5
        )

    def test_no_anchor_raises_rather_than_guessing_zero(self):
        """Defaulting to any instant would misplace every cut while looking perfectly plausible."""
        with pytest.raises(ValueError, match="No recording start time"):
            resolve_recording_t0()

    def test_a_duration_without_an_end_time_is_not_an_anchor(self):
        with pytest.raises(ValueError):
            resolve_recording_t0(recording_duration_seconds=600.0)


class TestACutIsAPeriodUnderReview:
    """One clip per span the operator held a shot in review — not per pause in the room.

    Grouping by silence produced three clips for the first shot, two for the second and one for
    the third on a meeting where the operator did exactly the same thing each time. The pauses
    measured 2.54s, 2.31s, 2.04s, 1.53s and 0.78s against a 2s threshold; which side of the line
    a breath landed on decided how many clips a shot got.
    """

    T0 = datetime(2026, 8, 27, 22, 10, 1, 71000, tzinfo=timezone.utc)
    SHOT_1, SHOT_2, SHOT_3 = 5720411, 5722946, 5723179

    # The real clicks, as offsets into the 76.4s recording: 19.80, 46.56, 62.80, cleared at 78.01.
    HISTORY = [
        {"version_id": SHOT_1, "since": "2026-08-27T22:10:20.869Z"},
        {"version_id": SHOT_2, "since": "2026-08-27T22:10:47.632Z"},
        {"version_id": SHOT_3, "since": "2026-08-27T22:11:03.869Z"},
        {"version_id": None, "since": "2026-08-27T22:11:19.080Z"},
    ]

    def _seg(self, segment_id, start_offset, end_offset, version_id):
        return StoredSegment(
            _id="m" + segment_id,
            segment_id=segment_id,
            playlist_id=462598,
            version_id=version_id,
            text="...",
            speaker="Cottalango Leon",
            language="en",
            absolute_start_time=(self.T0 + timedelta(seconds=start_offset)).isoformat(),
            absolute_end_time=(self.T0 + timedelta(seconds=end_offset)).isoformat(),
            vexa_updated_at=None,
            created_at=self.T0,
            updated_at=self.T0,
        )

    def _real_meeting(self):
        rows = [
            ("a", 25.06, 32.23, self.SHOT_1),
            ("b", 34.77, 37.33, self.SHOT_1),  # 2.54s pause — used to split
            ("c", 39.65, 43.48, self.SHOT_1),  # 2.31s pause — used to split
            ("d", 48.60, 50.64, self.SHOT_2),
            ("e", 51.42, 55.77, self.SHOT_2),  # 0.78s — did not split
            ("f", 57.81, 60.63, self.SHOT_2),  # 2.04s pause — used to split
            ("g", 64.99, 70.36, self.SHOT_3),
            ("h", 71.89, 75.48, self.SHOT_3),  # 1.53s — did not split
        ]
        by_version: dict[int, list[StoredSegment]] = {}
        for segment_id, start, end, version in rows:
            by_version.setdefault(version, []).append(
                self._seg(segment_id, start, end, version)
            )
        return by_version

    def _build(self, **over):
        kwargs = dict(
            recording_t0=self.T0,
            recording_duration_seconds=76.4,
            in_review_history=self.HISTORY,
        )
        kwargs.update(over)
        return {
            c.version_id: c
            for c in build_video_cuts_payload(self._real_meeting(), **kwargs)
        }

    def test_each_shot_gets_exactly_one_clip(self):
        """The whole point. Three shots, three clips — 3/2/1 was an artifact of the threshold."""
        built = self._build()

        assert [
            len(built[v].cuts) for v in (self.SHOT_1, self.SHOT_2, self.SHOT_3)
        ] == [
            1,
            1,
            1,
        ]

    def test_a_clip_runs_from_the_mark_to_the_switch(self):
        """Not from the first word to the last: the operator was on this shot for all of it, and
        pauses inside are part of watching it."""
        cut = self._build()[self.SHOT_1].cuts[0]

        assert round(cut.video_in_seconds, 2) == 19.80
        assert round(cut.video_out_seconds, 2) == 46.56

    def test_the_last_shot_runs_to_the_end_of_the_media(self):
        """The mark was cleared at 78.01s, but the recording stops at 76.4s — the bot leaves
        before the operator finishes tidying up, so the clip ends where the media does.
        """
        cut = self._build()[self.SHOT_3].cuts[0]

        assert round(cut.video_in_seconds, 2) == 62.80
        assert cut.video_out_seconds == 76.4

    def test_every_segment_of_a_period_is_carried_on_its_clip(self):
        assert self._build()[self.SHOT_1].cuts[0].transcript_segment_ids == [
            "a",
            "b",
            "c",
        ]

    def test_returning_to_a_shot_later_is_a_second_clip(self):
        """The one split that IS meaningful: the operator said so by marking it again."""
        history = self.HISTORY[:3] + [
            {"version_id": self.SHOT_1, "since": "2026-08-27T22:11:10.000Z"},
            {"version_id": None, "since": "2026-08-27T22:11:19.080Z"},
        ]
        by_version = self._real_meeting()
        by_version[self.SHOT_1].append(self._seg("z", 70.0, 73.0, self.SHOT_1))

        built = {
            c.version_id: c
            for c in build_video_cuts_payload(
                by_version,
                recording_t0=self.T0,
                recording_duration_seconds=76.4,
                in_review_history=history,
            )
        }

        assert len(built[self.SHOT_1].cuts) == 2
        assert round(built[self.SHOT_1].cuts[1].video_in_seconds, 2) == 68.93

    def test_a_period_where_nobody_spoke_produces_no_clip(self):
        """A shot on screen in silence has no discussion to play back."""
        history = self.HISTORY[:3] + [
            {"version_id": 999999, "since": "2026-08-27T22:11:10.000Z"},
            {"version_id": None, "since": "2026-08-27T22:11:19.080Z"},
        ]
        by_version = self._real_meeting()
        by_version[999999] = []

        built = {
            c.version_id: c
            for c in build_video_cuts_payload(
                by_version,
                recording_t0=self.T0,
                recording_duration_seconds=76.4,
                in_review_history=history,
            )
        }

        assert built[999999].cuts == []

    def test_a_clip_is_clamped_to_the_recording(self):
        """The mark can outlive the media — the bot stops recording before the operator moves on."""
        built = self._build(recording_duration_seconds=50.0)

        assert round(built[self.SHOT_1].cuts[0].video_out_seconds, 2) == 46.56
        assert built[self.SHOT_2].cuts[0].video_out_seconds == 50.0

    def test_without_a_timeline_there_are_no_clips(self):
        """The rule this replaced would have answered 3/2/1 here, from pauses of 2.54s, 2.31s,
        2.04s, 1.53s and 0.78s against a 2s line. Guessing boundaries from speech rhythm is worse
        than not answering: it looks like a considered division of the meeting."""
        built = self._build(in_review_history=None)

        assert [
            len(built[v].cuts) for v in (self.SHOT_1, self.SHOT_2, self.SHOT_3)
        ] == [0, 0, 0]
