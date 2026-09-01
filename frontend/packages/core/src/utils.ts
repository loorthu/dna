/**
 * Core utility functions
 */

import type { Playlist } from './interfaces';

/**
 * What to call a playlist on screen.
 *
 * ShotGrid puts the human name in `code` and leaves `name` off the entity entirely, so every
 * place that shows a playlist has to know to reach for `code` and to have something to say when
 * it is missing. One function so the picker and the title bar cannot disagree about what the same
 * playlist is called.
 */
export function playlistLabel(
  playlist: Pick<Playlist, 'id' | 'code'> | null | undefined
): string {
  if (!playlist) return '';
  return playlist.code?.trim() || `Playlist ${playlist.id}`;
}

/**
 * How many versions a playlist holds, for a list of playlists to choose from.
 *
 * Returns null when the backend didn't count, so an unknown number reads as silence rather than
 * as an empty playlist — the one thing a reviewer picking a playlist most needs told.
 */
export function versionCountLabel(
  count: number | undefined | null
): string | null {
  if (count === undefined || count === null) return null;
  if (count === 0) return 'empty';
  return count === 1 ? '1 version' : `${count} versions`;
}

/**
 * Formats a date string to a readable format (in UTC)
 */
export function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    timeZone: 'UTC',
  });
}

/**
 * Validates if a string is a valid URL
 */
export function isValidUrl(url: string): boolean {
  try {
    new URL(url);
    return true;
  } catch {
    return false;
  }
}
