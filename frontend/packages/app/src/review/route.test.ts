import { describe, it, expect, afterEach, vi } from 'vitest';
import { parseReviewRoute, currentReviewRoute } from './route';

/**
 * Which addresses belong to the review page.
 *
 * Null is the coordinator app's answer, so a mistake here does not show a broken review page —
 * it hands the reviewing tool a URL it knows nothing about, or takes one away from it. Both are
 * worse than a 404, which is why every near-miss below resolves to null rather than to a guess.
 */
describe('parseReviewRoute', () => {
  it('reads the name form the notes email sends', () => {
    expect(parseReviewRoute('/review/abc/dailies-comp-2026-08-30')).toEqual({
      kind: 'name',
      projectSlug: 'abc',
      playlistSlug: 'dailies-comp-2026-08-30',
      anchor: null,
    });
  });

  it('reads the id form', () => {
    expect(parseReviewRoute('/review/id/4471')).toEqual({
      kind: 'id',
      playlistId: 4471,
      anchor: null,
    });
  });

  it('carries the shot the link pointed at', () => {
    expect(
      parseReviewRoute('/review/abc/dailies', '#abc_0100_comp_v012')
    ).toMatchObject({ anchor: 'abc_0100_comp_v012' });
  });

  it('accepts a fragment without its hash', () => {
    expect(parseReviewRoute('/review/id/1', 'abc_0100')).toMatchObject({
      anchor: 'abc_0100',
    });
  });

  it('decodes escaped segments', () => {
    expect(parseReviewRoute('/review/abc/day%20one')).toMatchObject({
      playlistSlug: 'day one',
    });
  });

  it('leaves a half-escaped path alone rather than throwing out of a render', () => {
    expect(parseReviewRoute('/review/abc/day%2')).toMatchObject({
      playlistSlug: 'day%2',
    });
  });

  it.each([
    ['/', 'the coordinator app'],
    ['/review', 'the prefix on its own'],
    ['/review/', 'a trailing slash and nothing else'],
    ['/review/abc', 'a project with no playlist'],
    ['/review/abc/dailies/extra', 'more segments than the route has'],
    ['/reviewer/abc/dailies', 'a path that merely starts the same way'],
  ])('does not claim %s (%s)', (pathname) => {
    expect(parseReviewRoute(pathname)).toBeNull();
  });

  it.each([
    ['/review/id/abc', 'not a number at all'],
    [
      '/review/id/12abc',
      'nearly a number — likelier a typo than an instruction',
    ],
    ['/review/id/0', 'no playlist has id zero'],
    ['/review/id/-3', 'negative'],
  ])('rejects %s (%s)', (pathname) => {
    expect(parseReviewRoute(pathname)).toBeNull();
  });
});

/**
 * The same addresses when the app is mounted under a prefix. `parseReviewRoute` is unchanged and
 * still sees app-relative paths — `currentReviewRoute` takes the mount path off first — so this
 * covers the seam rather than re-testing the parser.
 */
describe('currentReviewRoute under a mount path', () => {
  const at = (base: string, pathname: string, hash = '') => {
    vi.stubEnv('BASE_URL', base);
    vi.stubGlobal('window', { location: { pathname, hash } });
  };

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it('reads a review address served at the root', () => {
    at('/', '/review/id/461876');
    expect(currentReviewRoute()).toEqual({
      kind: 'id',
      playlistId: 461876,
      anchor: null,
    });
  });

  it('reads the same address served under /dna/', () => {
    at('/dna/', '/dna/review/id/461876', '#shot_010');
    expect(currentReviewRoute()).toEqual({
      kind: 'id',
      playlistId: 461876,
      anchor: 'shot_010',
    });
  });

  it('leaves the coordinator app its own root', () => {
    at('/dna/', '/dna/');
    expect(currentReviewRoute()).toBeNull();
  });
});
