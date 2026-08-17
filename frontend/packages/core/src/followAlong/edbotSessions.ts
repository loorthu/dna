import type { ReviewSession, ReviewSessionUser } from './types';

/**
 * Session directory served by edbot, the review player's session broker.
 *
 * Shape of `GET {baseUrl}/edbotproxy/rest/show/{show}/sessions`:
 *
 * ```json
 * [{"id": "12", "name": "director_review",
 *   "connections": [{"c1": {"username": "jdoe"}}]}]
 * ```
 *
 * The whole file is an adapter for that one service; a site running a
 * different session directory supplies its own fetcher of `ReviewSession[]`.
 */

export interface FetchReviewSessionsOptions {
  baseUrl: string;
  show: string;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

interface RawSession {
  id?: unknown;
  name?: unknown;
  connections?: unknown;
}

function flattenConnections(connections: unknown): ReviewSessionUser[] {
  if (!Array.isArray(connections)) {
    return [];
  }

  const users: ReviewSessionUser[] = [];
  for (const connection of connections) {
    if (!connection || typeof connection !== 'object') {
      continue;
    }
    for (const [id, value] of Object.entries(
      connection as Record<string, unknown>
    )) {
      const username =
        value && typeof value === 'object'
          ? (value as { username?: unknown }).username
          : undefined;
      users.push({
        id,
        username: typeof username === 'string' ? username : '',
      });
    }
  }
  return users;
}

export function reviewSessionsUrl(baseUrl: string, show: string): string {
  const base = baseUrl.replace(/\/+$/, '');
  return `${base}/edbotproxy/rest/show/${encodeURIComponent(show)}/sessions`;
}

export async function fetchReviewSessions({
  baseUrl,
  show,
  signal,
  fetchImpl,
}: FetchReviewSessionsOptions): Promise<ReviewSession[]> {
  const doFetch = fetchImpl ?? fetch;
  const response = await doFetch(reviewSessionsUrl(baseUrl, show), { signal });

  if (!response.ok) {
    throw new Error(
      `Failed to list review sessions: ${response.status} ${response.statusText}`
    );
  }

  const body: unknown = await response.json();
  if (!Array.isArray(body)) {
    return [];
  }

  return body
    .filter(
      (session): session is RawSession =>
        !!session && typeof session === 'object'
    )
    .map((session) => ({
      id: String(session.id ?? ''),
      name: typeof session.name === 'string' ? session.name : '',
      users: flattenConnections(session.connections),
    }))
    .filter((session) => session.name !== '');
}

/** Sessions someone is watching sort first, then alphabetically. */
export function sortReviewSessions(sessions: ReviewSession[]): ReviewSession[] {
  return [...sessions].sort((a, b) => {
    if (a.users.length !== b.users.length) {
      return b.users.length - a.users.length;
    }
    return a.name.localeCompare(b.name);
  });
}
