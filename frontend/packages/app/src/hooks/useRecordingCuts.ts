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
 * the tab should notice without the viewer reloading. The other three are settled: their answer
 * cannot change until another meeting is recorded, and that changes the playlist metadata, which
 * refetches this anyway. Polling them would be asking a question nothing can answer differently.
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
 */
export function useRecordingCuts(playlistId: number | null) {
  return useQuery<PlaylistRecordingCuts, Error>({
    queryKey: ['recordingCuts', playlistId],
    queryFn: () => apiHandler.getRecordingCuts({ playlistId: playlistId! }),
    enabled: !!playlistId,
    refetchInterval: (query) => pollIntervalFor(query.state.data?.status),
  });
}
