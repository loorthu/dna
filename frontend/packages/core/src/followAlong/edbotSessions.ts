import type { ReviewSession, ReviewSessionUser } from './types';

/**
 * Session directory served by edbot, the review player's session broker.
 *
 * Shape of `GET {baseUrl}/edbotproxy/rest/show/{show}/sessions`, as observed
 * against a live server — `connections` is an object keyed by connection
 * token, not a list:
 *
 * ```json
 * [{"id": "fb170680-…", "name": "rounds",
 *   "connections": {
 *     "5925e191-…": {"username": "jdoe",
 *                    "position": {"cguid": "f5d1cc15-…", "shot": "taf0140"}}
 *   }}]
 * ```
 *
 * Only the session names and who is watching them are read: the directory
 * populates the picker, and nothing else depends on it being reachable.
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

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/** Reads one connection record into a user, whatever it is keyed by. */
function toUser(id: string, value: unknown): ReviewSessionUser {
  const record = (value ?? {}) as Record<string, unknown>;

  return {
    id: text(record.token).trim() || id,
    username: text(record.username),
  };
}

/**
 * Normalises the `connections` field into a flat user list.
 *
 * edbot keys connections by token in an object. Other directories (and older
 * edbot builds) have been seen sending a list of single-key wrappers, so both
 * are accepted rather than making the caller care.
 */
function flattenConnections(connections: unknown): ReviewSessionUser[] {
  if (!connections || typeof connections !== 'object') {
    return [];
  }

  if (Array.isArray(connections)) {
    const users: ReviewSessionUser[] = [];
    for (const connection of connections) {
      if (!connection || typeof connection !== 'object') {
        continue;
      }
      const record = connection as Record<string, unknown>;

      // A flat record carries its own fields; a wrapper nests them one deep
      // under the connection id.
      if ('username' in record || 'token' in record) {
        users.push(toUser(text(record.token), record));
        continue;
      }
      for (const [id, value] of Object.entries(record)) {
        users.push(toUser(id, value));
      }
    }
    return users;
  }

  return Object.entries(connections as Record<string, unknown>).map(
    ([id, value]) => toUser(id, value)
  );
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
