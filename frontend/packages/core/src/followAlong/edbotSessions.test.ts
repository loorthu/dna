import { describe, it, expect, vi } from 'vitest';
import {
  fetchReviewSessions,
  reviewSessionsUrl,
  sessionClipRef,
  sortReviewSessions,
} from './edbotSessions';

function jsonResponse(body: unknown, init: Partial<Response> = {}): Response {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    statusText: init.statusText ?? 'OK',
    json: async () => body,
  } as Response;
}

describe('reviewSessionsUrl', () => {
  it('builds the session directory URL', () => {
    expect(reviewSessionsUrl('http://edbot.test:8080', 'nite')).toBe(
      'http://edbot.test:8080/edbotproxy/rest/show/nite/sessions'
    );
  });

  it('tolerates a trailing slash on the base URL', () => {
    expect(reviewSessionsUrl('http://edbot.test:8080/', 'nite')).toBe(
      'http://edbot.test:8080/edbotproxy/rest/show/nite/sessions'
    );
  });

  it('encodes the show code', () => {
    expect(reviewSessionsUrl('http://edbot.test:8080', 'a b/c')).toContain(
      'show/a%20b%2Fc/sessions'
    );
  });
});

describe('fetchReviewSessions', () => {
  // Shape taken from a live edbot response: connections keyed by token, each
  // carrying the clip that connection is showing.
  it('flattens the token-keyed connections object into a users list', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse([
        {
          id: 'fb170680-34f8',
          name: 'rounds',
          connections: {
            '5925e191-57ff': {
              token: '5925e191-57ff',
              username: 'jdoe',
              hostname: 'dodo0050.example.com',
              position: { cguid: 'f5d1cc15', shot: 'taf0140' },
            },
            'aaaaaaaa-57ff': {
              token: 'aaaaaaaa-57ff',
              username: 'ak',
              position: { cguid: 'f5d1cc15', shot: 'taf0140' },
            },
          },
        },
      ])
    );

    const sessions = await fetchReviewSessions({
      baseUrl: 'http://edbot.test:8080',
      show: 'nite',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    expect(sessions).toEqual([
      {
        id: 'fb170680-34f8',
        name: 'rounds',
        users: [
          { id: '5925e191-57ff', username: 'jdoe', clipRef: 'f5d1cc15' },
          { id: 'aaaaaaaa-57ff', username: 'ak', clipRef: 'f5d1cc15' },
        ],
      },
    ]);
  });

  it('still accepts a list of single-key connection wrappers', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse([
        {
          id: 12,
          name: 'director_review',
          connections: [
            { c1: { username: 'jdoe' } },
            { c2: { username: 'ak' } },
          ],
        },
      ])
    );

    const sessions = await fetchReviewSessions({
      baseUrl: 'http://edbot.test:8080',
      show: 'nite',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    expect(sessions).toEqual([
      {
        id: '12',
        name: 'director_review',
        users: [
          { id: 'c1', username: 'jdoe' },
          { id: 'c2', username: 'ak' },
        ],
      },
    ]);
  });

  it('accepts a list of flat connection records', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse([
        {
          id: '7',
          name: 'flat',
          connections: [{ token: 'c9', username: 'jdoe' }],
        },
      ])
    );

    const sessions = await fetchReviewSessions({
      baseUrl: 'http://edbot.test:8080',
      show: 'nite',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    expect(sessions[0].users).toEqual([{ id: 'c9', username: 'jdoe' }]);
  });

  it('handles sessions with no connections', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse([{ id: '1', name: 'idle_room' }])
    );

    const sessions = await fetchReviewSessions({
      baseUrl: 'http://edbot.test:8080',
      show: 'nite',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    expect(sessions).toEqual([{ id: '1', name: 'idle_room', users: [] }]);
  });

  it('drops entries without a name', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse([{ id: '1' }, { id: '2', name: 'ok' }, null, 'junk'])
    );

    const sessions = await fetchReviewSessions({
      baseUrl: 'http://edbot.test:8080',
      show: 'nite',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    expect(sessions.map((s) => s.name)).toEqual(['ok']);
  });

  it('returns an empty list when the body is not an array', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ error: 'nope' }));

    await expect(
      fetchReviewSessions({
        baseUrl: 'http://edbot.test:8080',
        show: 'nite',
        fetchImpl: fetchImpl as unknown as typeof fetch,
      })
    ).resolves.toEqual([]);
  });

  it('throws on a non-ok response', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(null, { ok: false, status: 503, statusText: 'Unavailable' })
    );

    await expect(
      fetchReviewSessions({
        baseUrl: 'http://edbot.test:8080',
        show: 'nite',
        fetchImpl: fetchImpl as unknown as typeof fetch,
      })
    ).rejects.toThrow('503 Unavailable');
  });

  it('passes the abort signal through', async () => {
    const controller = new AbortController();
    const fetchImpl = vi.fn(async () => jsonResponse([]));

    await fetchReviewSessions({
      baseUrl: 'http://edbot.test:8080',
      show: 'nite',
      signal: controller.signal,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    expect(fetchImpl).toHaveBeenCalledWith(expect.any(String), {
      signal: controller.signal,
    });
  });
});

describe('sessionClipRef', () => {
  it('returns the clip the members agree on', () => {
    expect(
      sessionClipRef({
        id: '1',
        name: 'rounds',
        users: [
          { id: 'a', username: 'jdoe', clipRef: 'f5d1cc15' },
          { id: 'b', username: 'ak', clipRef: 'f5d1cc15' },
        ],
      })
    ).toBe('f5d1cc15');
  });

  it('takes the plurality when a member is out of sync', () => {
    expect(
      sessionClipRef({
        id: '1',
        name: 'rounds',
        users: [
          { id: 'a', username: 'jdoe', clipRef: 'f5d1cc15' },
          { id: 'b', username: 'ak', clipRef: 'f5d1cc15' },
          { id: 'c', username: 'late', clipRef: '7a2d3562' },
        ],
      })
    ).toBe('f5d1cc15');
  });

  it('keeps the first-seen clip on a tie, so polls do not flip', () => {
    const session = {
      id: '1',
      name: 'rounds',
      users: [
        { id: 'a', username: 'jdoe', clipRef: 'f5d1cc15' },
        { id: 'b', username: 'ak', clipRef: '7a2d3562' },
      ],
    };

    expect(sessionClipRef(session)).toBe('f5d1cc15');
    expect(sessionClipRef(session)).toBe('f5d1cc15');
  });

  it('returns null when nobody reports a clip', () => {
    expect(
      sessionClipRef({
        id: '1',
        name: 'idle',
        users: [{ id: 'a', username: 'jdoe' }],
      })
    ).toBeNull();
  });

  it('returns null for an empty session', () => {
    expect(sessionClipRef({ id: '1', name: 'idle', users: [] })).toBeNull();
  });
});

describe('sortReviewSessions', () => {
  it('sorts busy sessions first, then by name', () => {
    const sorted = sortReviewSessions([
      { id: '1', name: 'zulu', users: [] },
      { id: '2', name: 'alpha', users: [] },
      { id: '3', name: 'busy', users: [{ id: 'c1', username: 'jdoe' }] },
    ]);

    expect(sorted.map((s) => s.name)).toEqual(['busy', 'alpha', 'zulu']);
  });

  it('does not mutate the input', () => {
    const input = [
      { id: '1', name: 'zulu', users: [] },
      { id: '2', name: 'alpha', users: [] },
    ];
    sortReviewSessions(input);

    expect(input.map((s) => s.name)).toEqual(['zulu', 'alpha']);
  });
});
