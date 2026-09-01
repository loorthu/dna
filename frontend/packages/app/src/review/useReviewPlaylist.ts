import { useQuery } from '@tanstack/react-query';
import type { ReviewPlaylist, ReviewResolution } from '@dna/core';
import { apiHandler } from '../api';
import type { ReviewRoute } from './route';

/**
 * The two steps a review link takes, as two queries.
 *
 * A name-shaped address has to be resolved before the page can be fetched, and the resolution is
 * worth its own cache entry: it is the slow half (it lists the show's playlists), it changes far
 * less often than the page's contents, and when it comes back ambiguous there is no page to fetch
 * at all — the reader is shown the choice instead.
 *
 * Nothing here polls. The page is a record of a review that already happened; a transcript that
 * grows while someone reads it belongs to the coordinator's tool, not to this one.
 */

export function useReviewResolution(route: ReviewRoute | null) {
  const enabled = route?.kind === 'name';
  return useQuery<ReviewResolution, Error>({
    queryKey: [
      'reviewResolution',
      route?.kind === 'name' ? route.projectSlug : null,
      route?.kind === 'name' ? route.playlistSlug : null,
    ],
    queryFn: () =>
      apiHandler.resolveReviewAddress({
        projectSlug: (route as { projectSlug: string }).projectSlug,
        playlistSlug: (route as { playlistSlug: string }).playlistSlug,
      }),
    enabled,
    retry: false,
  });
}

export function useReviewPlaylist(playlistId: number | null) {
  return useQuery<ReviewPlaylist, Error>({
    queryKey: ['reviewPlaylist', playlistId],
    queryFn: () => apiHandler.getReviewPlaylist({ playlistId: playlistId! }),
    enabled: playlistId != null,
    retry: false,
  });
}

/**
 * Which playlist the route names, once resolution has had its say.
 *
 * `null` means "not yet, or not one": the id form answers immediately, the name form waits for
 * the resolver, and an ambiguous name never answers — that case is a choice for the reader, and
 * returning the first match here is exactly the guess the resolver refused to make.
 */
export function resolvedPlaylistId(
  route: ReviewRoute | null,
  resolution: ReviewResolution | undefined
): number | null {
  if (route?.kind === 'id') return route.playlistId;
  return resolution?.playlist_id ?? null;
}
