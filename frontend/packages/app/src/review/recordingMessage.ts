import type { ReviewRecording } from '@dna/core';

/**
 * What to say when there is nothing to play, and how to say a time.
 *
 * Kept apart from the player so the rule can be tested as a rule — the same reason
 * `transcriptStatus` and `noteStatus` are their own files.
 */

export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return `${minutes}:${String(rest).padStart(2, '0')}`;
}

/**
 * The same distinctions the coordinator's player draws, said to a different reader.
 *
 * An artist cannot start a bot or chase a collector, so each message ends at what they can expect
 * rather than at what somebody ought to do — "tick Record this meeting next time" is advice for
 * the person running the review, and telling it to the person waiting on the video reads as being
 * blamed for a setting they have never seen.
 *
 * `disabled` is the one status the coordinator's player has no equivalent for: this deployment
 * has no recording pipeline at all, which is neither a fault nor a wait.
 */
export function recordingMessage(
  status: ReviewRecording['status'],
  hasCuts: boolean
): string | null {
  switch (status) {
    case 'disabled':
      return 'Meeting recordings are not kept on this system.';
    case 'no_meeting':
      return 'No meeting has run on this playlist.';
    case 'no_recording':
      return 'This meeting was not recorded.';
    case 'pending':
      return 'The meeting is being recorded now. The video appears here once it ends.';
    case 'archiving':
      return 'The recording is still being collected. Try again in a minute.';
    case 'blocked':
      // Deliberately without the reason the coordinator's player shows. That reason names a
      // directory on a share this reader has never seen and cannot create, so quoting it here
      // would read as an instruction they are unable to follow. What they can act on is that
      // the video is coming and is not lost.
      return 'The recording has not been saved to the share yet. It is safe, and appears here once that is sorted out.';
    case 'no_segments':
      return 'A recording exists, but nothing was transcribed against these shots.';
    case 'ready':
      return hasCuts
        ? null
        : 'This shot was not discussed in the meeting recording.';
    default:
      return null;
  }
}
