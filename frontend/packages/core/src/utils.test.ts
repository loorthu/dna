import { describe, it, expect } from 'vitest';
import {
  formatDate,
  isValidUrl,
  playlistLabel,
  versionCountLabel,
} from './utils';

describe('utils', () => {
  describe('playlistLabel', () => {
    it('uses the code, which is where ShotGrid keeps the human name', () => {
      expect(
        playlistLabel({ id: 461876, code: 'NITE: Modeling AM Dailies' })
      ).toBe('NITE: Modeling AM Dailies');
    });

    it.each([
      ['missing', undefined],
      ['empty', ''],
      ['blank', '   '],
    ])('falls back to the id when the code is %s', (_case, code) => {
      // A blank name would render as an empty title bar, which is worse than no title bar at all:
      // it looks like the app failed to load rather than like the playlist has no name.
      expect(playlistLabel({ id: 461876, code })).toBe('Playlist 461876');
    });

    it('has nothing to say about no playlist', () => {
      expect(playlistLabel(null)).toBe('');
    });
  });

  describe('versionCountLabel', () => {
    it.each([
      [4, '4 versions'],
      [1, '1 version'],
      [0, 'empty'],
    ])('says what %s versions is', (count, expected) => {
      expect(versionCountLabel(count)).toBe(expected);
    });

    it.each([
      ['undefined', undefined],
      ['null', null],
    ])('says nothing when the count is %s', (_case, count) => {
      // An uncounted playlist is not an empty one, and a picker that called it "empty" would
      // steer people away from the playlist they came for.
      expect(versionCountLabel(count)).toBeNull();
    });
  });

  describe('formatDate', () => {
    it('should format a date string correctly', () => {
      const dateString = '2024-01-15T10:30:00Z';
      const formatted = formatDate(dateString);
      expect(formatted).toContain('January');
      expect(formatted).toContain('2024');
      expect(formatted).toContain('15');
    });

    it('should handle different date formats', () => {
      const dateString = '2024-12-25T00:00:00Z';
      const formatted = formatDate(dateString);
      expect(formatted).toContain('December');
      expect(formatted).toContain('25');
    });
  });

  describe('isValidUrl', () => {
    it('should return true for valid URLs', () => {
      expect(isValidUrl('https://example.com')).toBe(true);
      expect(isValidUrl('http://example.com')).toBe(true);
      expect(isValidUrl('https://example.com/path?query=value')).toBe(true);
    });

    it('should return false for invalid URLs', () => {
      expect(isValidUrl('not-a-url')).toBe(false);
      expect(isValidUrl('')).toBe(false);
      expect(isValidUrl('just text')).toBe(false);
    });
  });
});
