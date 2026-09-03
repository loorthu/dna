import { describe, it, expect, afterEach, vi } from 'vitest';

import { basePath, withBase, stripBase } from './basePath';

/**
 * Both halves matter. The prefixed cases are what a sub-path deployment needs; the `/` cases are
 * the guarantee that adding this changed nothing for a root-served one, which is every other
 * deployment of DNA.
 */
function mountedAt(base: string) {
  vi.stubEnv('BASE_URL', base);
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('basePath', () => {
  it('is / by default', () => {
    expect(basePath()).toBe('/');
  });

  it('normalises a prefix to leading and trailing slashes', () => {
    for (const raw of ['/dna/', '/dna', 'dna/', 'dna', '  /dna/  ']) {
      mountedAt(raw);
      expect(basePath()).toBe('/dna/');
    }
  });

  it('reads an empty base as the root', () => {
    mountedAt('');
    expect(basePath()).toBe('/');
  });
});

describe('withBase', () => {
  it('is the identity at the root', () => {
    mountedAt('/');
    expect(withBase('/recordings/kpop/20260901/a.mp4')).toBe(
      '/recordings/kpop/20260901/a.mp4'
    );
    expect(withBase('/review/nite/dailies')).toBe('/review/nite/dailies');
  });

  it('moves a root-relative URL under the mount path', () => {
    mountedAt('/dna/');
    expect(withBase('/recordings/kpop/20260901/a.mp4')).toBe(
      '/dna/recordings/kpop/20260901/a.mp4'
    );
  });

  it('leaves absolute and relative URLs alone', () => {
    mountedAt('/dna/');
    expect(withBase('https://elsewhere/x.mp4')).toBe('https://elsewhere/x.mp4');
    expect(withBase('recordings/a.mp4')).toBe('recordings/a.mp4');
  });

  it('does not prefix twice', () => {
    mountedAt('/dna/');
    expect(withBase('/dna/recordings/a.mp4')).toBe('/dna/recordings/a.mp4');
    expect(withBase('/dna')).toBe('/dna');
  });
});

describe('stripBase', () => {
  it('is the identity at the root', () => {
    mountedAt('/');
    expect(stripBase('/review/nite/dailies')).toBe('/review/nite/dailies');
  });

  it('removes the mount path', () => {
    mountedAt('/dna/');
    expect(stripBase('/dna/review/nite/dailies')).toBe('/review/nite/dailies');
    expect(stripBase('/dna/')).toBe('/');
    expect(stripBase('/dna')).toBe('/');
  });

  it('leaves a pathname outside the mount alone, so it simply will not match', () => {
    mountedAt('/dna/');
    expect(stripBase('/review/nite/dailies')).toBe('/review/nite/dailies');
  });
});
