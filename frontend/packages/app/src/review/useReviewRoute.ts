import { useEffect, useState } from 'react';
import { currentReviewRoute, type ReviewRoute } from './route';

/**
 * The review route the browser is currently on, or null for the coordinator app.
 *
 * There is no in-app navigation between the two — the review page's own links are plain anchors
 * that reload — so this exists mainly to answer the question once, at mount. It listens for
 * `popstate` and `hashchange` anyway, because the back button after following a shot link is the
 * one case where the address changes under a mounted page, and a stale answer there would leave
 * the reader looking at a page that no longer matches the URL.
 */
export function useReviewRoute(): ReviewRoute | null {
  const [route, setRoute] = useState<ReviewRoute | null>(currentReviewRoute);

  useEffect(() => {
    const update = () => setRoute(currentReviewRoute());
    window.addEventListener('popstate', update);
    window.addEventListener('hashchange', update);
    return () => {
      window.removeEventListener('popstate', update);
      window.removeEventListener('hashchange', update);
    };
  }, []);

  return route;
}
