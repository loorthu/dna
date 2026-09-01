import { useCallback, useRef } from 'react';

/**
 * Seeking a <video> that may not know its duration yet.
 *
 * Setting `currentTime` before the browser has metadata is a silent no-op — no error, no throw,
 * the clip simply plays from zero. Both players that jump into a meeting recording hit this on
 * first paint, because the seek they want is the one they issue before the file has loaded, so
 * the request is held and flushed on `loadedmetadata`.
 *
 * Only the holding is shared. What the two players do afterwards is deliberately different: the
 * coordinator's cut player pauses at each span's out-point, and the artist review page does not —
 * an artist following a link to their shot is expected to keep watching past it.
 */
export function useVideoSeek(
  videoRef: React.RefObject<HTMLVideoElement | null>
) {
  const pendingSeekRef = useRef<number | null>(null);

  const seekTo = useCallback(
    (seconds: number) => {
      const video = videoRef.current;
      if (!video) return;
      // readyState >= HAVE_METADATA (1) means duration is known and currentTime will take.
      if (video.readyState >= 1) {
        video.currentTime = seconds;
      } else {
        pendingSeekRef.current = seconds;
      }
    },
    [videoRef]
  );

  const onLoadedMetadata = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const pending = pendingSeekRef.current;
    if (pending != null) {
      pendingSeekRef.current = null;
      video.currentTime = pending;
    }
  }, [videoRef]);

  return { seekTo, onLoadedMetadata };
}
