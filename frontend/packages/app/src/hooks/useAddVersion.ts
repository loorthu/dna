import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiHandler } from '../api';
import type {
  AddVersionOutcome,
  AddVersionsToPlaylistParams,
  AddVersionsToPlaylistResponse,
} from '@dna/core';

/**
 * Pull the review ids out of whatever was pasted.
 *
 * People arrive with a column copied out of a spreadsheet, a comma-separated line off a turnover
 * sheet, or the bracketed prefixes of version names. Reading every run of digits takes all three
 * without asking anyone to reformat it first.
 */
export function parseJtsNumbers(text: string): number[] {
  const found = text.match(/\d+/g) ?? [];
  return [...new Set(found.map(Number))];
}

export const useAddVersionsToPlaylist = () => {
  const queryClient = useQueryClient();

  return useMutation<
    AddVersionsToPlaylistResponse,
    Error,
    AddVersionsToPlaylistParams
  >({
    mutationFn: (params) => apiHandler.addVersionsToPlaylist(params),
    onSuccess: (_, variables) => {
      // The sidebar's version list, and the counts the playlist menu prints beside every
      // playlist on the show -- one of which is now longer.
      queryClient.invalidateQueries({
        queryKey: ['versions', variables.playlistId],
      });
      queryClient.invalidateQueries({ queryKey: ['playlists'] });
    },
  });
};

type ToastType = 'info' | 'success' | 'warning' | 'error';

export interface AddVersionsSummary {
  title: string;
  description: string;
  type: ToastType;
}

function nameList(labels: string[], limit = 3): string {
  if (labels.length <= limit) {
    return labels.join(', ');
  }
  return `${labels.slice(0, limit).join(', ')} and ${labels.length - limit} more`;
}

/**
 * Say what became of a paste in one line, for a toast.
 *
 * A pasted list rarely comes back all one way -- some land, some were already in the review, some
 * are stale ids off an old turnover sheet. The counts alone would hide that, so the ones that did
 * not land are named: those are the numbers somebody has to go and check.
 */
export function summariseAddOutcomes(
  outcomes: AddVersionOutcome[]
): AddVersionsSummary {
  const added = outcomes.filter((o) => o.status === 'added');
  const already = outcomes.filter((o) => o.status === 'already_in_playlist');
  const missing = outcomes.filter((o) => o.status === 'not_found');

  const notes: string[] = [];
  if (already.length) {
    notes.push(
      `${nameList(already.map((o) => String(o.jts)))} already in the playlist`
    );
  }
  if (missing.length) {
    notes.push(
      `${nameList(missing.map((o) => String(o.jts)))} not on this show`
    );
  }

  if (!added.length) {
    return {
      title: missing.length ? 'Nothing added' : 'Already in this playlist',
      description: `${notes.join('; ')}.`,
      type: missing.length ? 'error' : 'info',
    };
  }

  const names = nameList(added.map((o) => o.version_name || String(o.jts)));
  return {
    title:
      added.length === 1 ? 'Version added' : `${added.length} versions added`,
    description: notes.length ? `${names}. ${notes.join('; ')}.` : `${names}.`,
    type: missing.length ? 'warning' : 'success',
  };
}
