/**
 * Where this build of the app is mounted, and the two things that follow from it.
 *
 * DNA is served at the root by default, and upstream it always is. A site serving it under a
 * prefix — SPI mounts it at `/dna/` beside its other ShotGrid tools — builds with
 * `VITE_BASE_PATH`, which `vite.config.ts` passes to Vite's `base` and Vite exposes back here as
 * `import.meta.env.BASE_URL`. Reading it from there rather than from a `VITE_` variable of our
 * own keeps ONE value: the same one Vite already used to rewrite every asset URL in the bundle,
 * so the two can never disagree.
 *
 * What needs this is the set of addresses Vite does NOT rewrite, because they are built by the
 * BACKEND: `media_url` for a recording and `url_path` for a review link. Those are root-relative
 * by construction — one backend serves more than one front end and cannot know where any of them
 * is mounted — so the prefix is applied here, at the point of use.
 *
 * Every function below is the identity when the base is `/`, which is what lets the call sites be
 * unconditional and leaves a root-mounted deployment behaving exactly as it did.
 */

function normalize(raw: string | undefined): string {
  const trimmed = (raw ?? '/').trim();
  if (!trimmed || trimmed === '/') return '/';
  const leading = trimmed.startsWith('/') ? trimmed : `/${trimmed}`;
  return leading.endsWith('/') ? leading : `${leading}/`;
}

/** The mount path, always with a leading and a trailing slash. `/` when mounted at the root. */
export function basePath(): string {
  return normalize(import.meta.env.BASE_URL);
}

/**
 * A root-relative URL from the backend, moved under the mount path.
 *
 * Anything absolute (`https://…`) or already relative is returned untouched, as is a URL that
 * already carries the prefix: prefixing twice would produce `/dna/dna/…`, which fails as a 404
 * a long way from whatever caused it.
 */
export function withBase(url: string): string {
  const base = basePath();
  if (base === '/' || !url.startsWith('/')) return url;
  if (url === base.slice(0, -1) || url.startsWith(base)) return url;
  return `${base}${url.slice(1)}`;
}

/**
 * A pathname with the mount path removed, so route matching can be written as if mounted at `/`.
 *
 * The inverse of `withBase` for the one direction the app reads rather than writes: the address
 * bar. A pathname that is not under the mount is returned as-is and simply will not match.
 */
export function stripBase(pathname: string): string {
  const base = basePath();
  if (base === '/') return pathname;
  if (pathname === base.slice(0, -1)) return '/';
  if (!pathname.startsWith(base)) return pathname;
  return pathname.slice(base.length - 1);
}
