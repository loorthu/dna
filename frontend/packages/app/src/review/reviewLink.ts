import type { ReviewLink } from '@dna/core';

import { withBase } from '../basePath';

/**
 * The address of one shot on the artist page, for the reviewing tool's button.
 *
 * Kept as a function rather than inlined because of what it must NOT do: invent an anchor. If the
 * backend has no fragment for this version — a playlist whose versions changed since the link was
 * fetched, most likely — the answer is the playlist page, which is right, rather than a guessed
 * `#name` that scrolls nowhere and silently does nothing when clicked.
 *
 * Null when there is no link at all, so the caller can hide the button rather than offer one that
 * goes to `#`.
 */
export function reviewShotHref(
  link: ReviewLink | undefined,
  versionId: number | null | undefined
): string | null {
  if (!link?.url_path) return null;
  const anchor =
    versionId != null ? link.anchors[String(versionId)] : undefined;
  // The backend builds this root-relative; withBase moves it under the mount path, and is the
  // identity for a root-served deployment.
  const path = withBase(link.url_path);
  return anchor ? `${path}#${anchor}` : path;
}
