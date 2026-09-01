import { describe, it, expect } from 'vitest';
import { parseReviewRoute } from './route';

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
