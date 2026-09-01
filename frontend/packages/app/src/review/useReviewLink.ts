import { useQuery } from '@tanstack/react-query';
import type { ReviewLink } from '@dna/core';
import { apiHandler } from '../api';

/**
 * Where this playlist's artist page is, asked once.
 *
 * Keyed on the playlist alone, because that is what the answer is about: the coordinator walks
 * the playlist's versions one at a time, and re-asking on every version change would put a
 * ShotGrid round trip behind an arrow key.
 *
 * Failure is silent by design. This backs one optional button in a tool whose job is taking
 * notes; a deployment running an older backend answers 404 here, and the right consequence of
 * that is no button, not an error the note-taker has to dismiss mid-review.
 */
export function useReviewLink(playlistId: number | null | undefined) {
  return useQuery<ReviewLink, Error>({
    queryKey: ['reviewLink', playlistId ?? null],
    queryFn: () => apiHandler.getReviewLink({ playlistId: playlistId! }),
    enabled: playlistId != null,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}
