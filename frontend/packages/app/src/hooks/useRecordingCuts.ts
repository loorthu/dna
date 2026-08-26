import { useQuery } from '@tanstack/react-query';
import type { PlaylistRecordingCuts } from '@dna/core';
import { apiHandler } from '../api';

/**
 * How often to re-ask while the answer is still moving.
 *
 * A recording is only unavailable for as long as the meeting runs plus the seconds the collector
 * needs to take custody — measured at about a second for a short meeting, twenty for a long one.
 * Ten seconds keeps the tab honest without turning an open playlist into a polling client.
 */
const IN_FLIGHT_POLL_MS = 10_000;

/**
 * How often to re-ask, given what the last answer said — or `false` to stop.
 *
 * Exported so the rule can be tested as a rule. Asserting it through the hook meant inspecting
 * TanStack's internals, which produced assertions that passed whatever the code did.
 *
 * `pending` (being recorded) and `archiving` (collector still working) resolve on their own, so
 * the tab should notice without the viewer reloading. The rest are settled FOR THE MEETING THEY
 * DESCRIBE and are never polled — a new meeting changes the query key instead, which is the only
 * thing that can change their answer.
 *
 * That distinction is load-bearing. `no_meeting` is the answer every playlist gives before its
 * bot is dispatched, and it is the answer the panel gets on mount, seconds before the dispatch it
 * was opened to make. Polling it would be one fix; keying on the meeting is the better one,
 * because it also catches the second meeting on a playlist that already has a recording.
 */
export function pollIntervalFor(
  status: PlaylistRecordingCuts['status'] | undefined
): number | false {
  return status === 'pending' || status === 'archiving'
    ? IN_FLIGHT_POLL_MS
    : false;
}

/**
 * The meeting recording for a playlist: where the media is, and which spans discussed each version.
 *
 * `vexaMeetingId` is part of the key rather than an argument to the request. The answer is about
 * one meeting, so when the playlist moves to another meeting the cached one is not stale — it is
 * about something else, and TanStack fetches for the new key on its own. Without it, a panel that
 * mounted before the dispatch kept serving its pre-dispatch "no meeting" answer for the rest of
 * the meeting, which is exactly how a recorded meeting came to report itself unrecorded.
 */
export function useRecordingCuts(
  playlistId: number | null,
  vexaMeetingId?: number | null
) {
  return useQuery<PlaylistRecordingCuts, Error>({
    queryKey: ['recordingCuts', playlistId, vexaMeetingId ?? null],
    queryFn: () => apiHandler.getRecordingCuts({ playlistId: playlistId! }),
    enabled: !!playlistId,
    refetchInterval: (query) => pollIntervalFor(query.state.data?.status),
  });
}
