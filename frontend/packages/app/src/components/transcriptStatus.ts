export type StatusTone = 'live' | 'stale' | 'idle';

/**
 * What the status bar says about this playlist's transcript, and how to colour its dot.
 *
 * The bar describes the TRANSCRIPTION; it used to describe the app's own event socket. That socket
 * is up from the moment the app loads, so an empty transcript read "Connected - waiting for
 * transcript" on every playlist nobody had dispatched a bot to — a sentence that promises words are
 * coming when nothing is listening for any. Whether a bot is in the meeting is the fact being
 * reported, and `botLive` is the only thing that can answer it.
 *
 * The socket still matters, but only once a bot IS live: there it is the difference between hearing
 * the meeting and having lost the feed while it carries on. With no bot it qualifies nothing, so it
 * is not mentioned — a reconnecting socket is not news to someone who is not transcribing anything.
 *
 * Segments already in hand are named in every state: they are a record of a meeting that happened,
 * and they do not stop being real when the bot leaves.
 */
export function transcriptStatus(
  botLive: boolean,
  isConnected: boolean,
  segmentCount: number
): { tone: StatusTone; label: string } {
  const tally = `${segmentCount} segment${segmentCount === 1 ? '' : 's'}`;

  if (!botLive) {
    return {
      tone: 'idle',
      label: segmentCount > 0 ? tally : 'No bot in this meeting',
    };
  }

  if (!isConnected) {
    return {
      tone: 'stale',
      label: segmentCount > 0 ? `Reconnecting... • ${tally}` : 'Reconnecting...',
    };
  }

  return {
    tone: 'live',
    label:
      segmentCount > 0
        ? `Live • ${tally}`
        : 'Connected - waiting for transcript',
  };
}
