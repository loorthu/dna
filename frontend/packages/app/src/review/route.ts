/**
 * The one route this app has.
 *
 * DNA is otherwise a single screen whose state lives in React — you sign in, you pick a project
 * and a playlist, and nothing about that is in the address bar. The artist review page cannot
 * work that way: it exists to be linked to from an email, so the shot someone clicked has to
 * survive a cold load, a sign-in redirect and a refresh.
 *
 * That is one route, not an app-wide router. Parsing it here keeps the dependency at zero and
 * leaves the coordinator app exactly as it was — it still owns `/`, still keeps its selection in
 * state, and never consults this file.
 *
 * Two shapes resolve, and the second is the reason the first can stay readable:
 *
 *   /review/<project>/<playlist>   the name form, which is what the email sends
 *   /review/id/<playlist_id>       the id form, which always resolves
 *
 * The id form is not a fallback the email chooses at random: it is what a playlist with no usable
 * name gets, and where the page sends someone whose name-shaped link turned out to match several
 * playlists. `id` is therefore a reserved first segment and cannot be a project.
 */

export const REVIEW_PREFIX = '/review';
export const REVIEW_ID_SEGMENT = 'id';

export interface ReviewByIdRoute {
  kind: 'id';
  playlistId: number;
  /** The shot to scroll to, from the URL fragment — absent when the link was to the playlist. */
  anchor: string | null;
}

export interface ReviewByNameRoute {
  kind: 'name';
  projectSlug: string;
  playlistSlug: string;
  anchor: string | null;
}

export type ReviewRoute = ReviewByIdRoute | ReviewByNameRoute;

/**
 * Parse a location into a review route, or null when this is not one.
 *
 * Null is the coordinator app's answer: every path that is not a review address belongs to it,
 * including `/review` on its own and `/review/id/not-a-number`. Erroring on a malformed review
 * URL would replace one wrong page with a worse one.
 */
export function parseReviewRoute(
  pathname: string,
  hash: string = ''
): ReviewRoute | null {
  if (!pathname.startsWith(`${REVIEW_PREFIX}/`)) return null;

  const segments = pathname
    .slice(REVIEW_PREFIX.length + 1)
    .split('/')
    .filter(Boolean)
    .map(decodeSegment);

  if (segments.length !== 2) return null;
  const [first, second] = segments;
  const anchor = parseAnchor(hash);

  if (first === REVIEW_ID_SEGMENT) {
    // Deliberately strict: `Number('12abc')` is NaN but `parseInt` would take the 12, and a URL
    // that is nearly an id is likelier to be a typo than an instruction.
    const playlistId = /^\d+$/.test(second) ? Number(second) : NaN;
    return Number.isFinite(playlistId) && playlistId > 0
      ? { kind: 'id', playlistId, anchor }
      : null;
  }

  if (!first || !second) return null;
  return { kind: 'name', projectSlug: first, playlistSlug: second, anchor };
}

/** The current route, read from `window.location`. */
export function currentReviewRoute(): ReviewRoute | null {
  if (typeof window === 'undefined') return null;
  return parseReviewRoute(window.location.pathname, window.location.hash);
}

function decodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    // A half-escaped path is still a path. Taking it verbatim lets the resolver decide it does
    // not match anything, rather than throwing out of a render.
    return segment;
  }
}

function parseAnchor(hash: string): string | null {
  const value = hash.startsWith('#') ? hash.slice(1) : hash;
  if (!value) return null;
  return decodeSegment(value);
}
