import { describe, it, expect } from 'vitest';
import { findByExternalRef } from './findByExternalRef';

const versions = [
  { id: 1, external_ref: '100' },
  { id: 2, external_ref: '200' },
  { id: 3 },
  { id: 4, external_ref: null },
];

describe('findByExternalRef', () => {
  it('finds the entity carrying the ref', () => {
    expect(findByExternalRef(versions, '200')?.id).toBe(2);
  });

  it('returns null when nothing matches', () => {
    expect(findByExternalRef(versions, '999')).toBeNull();
  });

  it('returns null for an empty or missing ref', () => {
    expect(findByExternalRef(versions, '')).toBeNull();
    expect(findByExternalRef(versions, '  ')).toBeNull();
    expect(findByExternalRef(versions, null)).toBeNull();
    expect(findByExternalRef(versions, undefined)).toBeNull();
  });

  it('matches a numeric ref against a string announcement', () => {
    expect(findByExternalRef([{ id: 7, external_ref: 42 }], '42')?.id).toBe(7);
  });

  it('trims whitespace on both sides', () => {
    expect(
      findByExternalRef([{ id: 7, external_ref: ' 42 ' }], ' 42 ')?.id
    ).toBe(7);
  });

  it('does not treat a leading-zero ref as numerically equal', () => {
    expect(
      findByExternalRef([{ id: 7, external_ref: '42' }], '042')
    ).toBeNull();
  });

  it('skips entities with no ref', () => {
    expect(
      findByExternalRef([{ id: 3 }, { id: 4, external_ref: null }], '3')
    ).toBeNull();
  });

  it('returns the first match when refs are duplicated', () => {
    expect(
      findByExternalRef(
        [
          { id: 1, external_ref: '5' },
          { id: 2, external_ref: '5' },
        ],
        '5'
      )?.id
    ).toBe(1);
  });
});
