import { describe, it, expect } from 'vitest';
import type { ReviewLink } from '@dna/core';
import { reviewShotHref } from './reviewLink';

const LINK: ReviewLink = {
  playlist_id: 4471,
  url_path: '/review/nite/dailies-comp-2026-08-30',
  anchors: { '900': 'abc_0100_comp_v012', '901': 'abc_0110_comp_v004' },
};

describe('reviewShotHref', () => {
  it('addresses the shot being reviewed', () => {
    expect(reviewShotHref(LINK, 901)).toBe(
      '/review/nite/dailies-comp-2026-08-30#abc_0110_comp_v004'
    );
  });

  it('falls back to the playlist when the version has no anchor', () => {
    // A guessed fragment scrolls nowhere and fails silently; the playlist page is at least right.
    expect(reviewShotHref(LINK, 999)).toBe(
      '/review/nite/dailies-comp-2026-08-30'
    );
  });

  it('falls back to the playlist when no version is selected', () => {
    expect(reviewShotHref(LINK, null)).toBe(
      '/review/nite/dailies-comp-2026-08-30'
    );
    expect(reviewShotHref(LINK, undefined)).toBe(
      '/review/nite/dailies-comp-2026-08-30'
    );
  });

  it('is null with no link, so the button can be hidden rather than dead', () => {
    expect(reviewShotHref(undefined, 900)).toBeNull();
    expect(reviewShotHref({ ...LINK, url_path: '' }, 900)).toBeNull();
  });
});
