import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import styled from 'styled-components';
import type { PlaylistRecordingCuts, RecordingCut } from '@dna/core';
import { useVideoSeek } from '../hooks/useVideoSeek';
import { withBase } from '../basePath';

/**
 * The meeting recording, scrubbed to the spans that discussed one version.
 *
 * VIRTUAL cuts: there is one file and nothing is rendered. Playing a "clip" means seeking a
 * <video> to the cut's in-point and pausing at its out-point, which is why nginx serving the
 * archive with Range support is load-bearing — without 206s the browser cannot seek and every
 * clip would start from the beginning of the meeting.
 */

const Wrapper = styled.div`
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
`;

const Video = styled.video`
  width: 100%;
  max-height: 45vh;
  background: #000;
  border-radius: ${({ theme }) => theme.radii.md};
`;

const ClipRow = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
`;

const ClipButton = styled.button<{ $active: boolean }>`
  padding: 4px 10px;
  font-size: 12px;
  font-family: ${({ theme }) => theme.fonts.sans};
  border-radius: ${({ theme }) => theme.radii.md};
  cursor: pointer;
  color: ${({ theme, $active }) =>
    $active ? theme.colors.text.primary : theme.colors.text.secondary};
  background: ${({ theme, $active }) =>
    $active ? theme.colors.bg.surfaceHover : 'transparent'};
  border: 1px solid
    ${({ theme, $active }) =>
      $active ? theme.colors.border.strong : theme.colors.border.default};

  &:hover {
    background: ${({ theme }) => theme.colors.bg.surfaceHover};
  }
`;

const Empty = styled.div`
  padding: 20px 12px;
  font-size: 13px;
  line-height: 1.5;
  color: ${({ theme }) => theme.colors.text.secondary};
`;

/**
 * The one empty state that is a FAULT rather than a wait, so the one that does not get the muted
 * grey the others share.
 *
 * Every other message here says "come back later" and reads correctly as quiet informational
 * text. This one is the opposite: nothing will happen until a person does something, and set in
 * the same grey it was routinely read as more of the same and scrolled past. Amber rather than
 * red because nothing is broken or lost — the recording is safe upstream, it just is not filed.
 */
const Alert = styled.div`
  margin: 12px;
  padding: 12px 14px;
  border: 1px solid ${({ theme }) => theme.colors.status.warning};
  border-left-width: 4px;
  border-radius: ${({ theme }) => theme.radii.md};
  background: ${({ theme }) => theme.colors.status.warningSubtle};
  color: ${({ theme }) => theme.colors.status.warning};
  font-size: 13px;
  line-height: 1.5;
`;

const AlertHeading = styled.div`
  font-weight: 600;
  margin-bottom: 4px;
`;

const Meta = styled.div`
  font-size: 11px;
  color: ${({ theme }) => theme.colors.text.muted};
`;

function formatSpan(cut: RecordingCut): string {
  const seconds = Math.max(0, cut.video_out_seconds - cut.video_in_seconds);
  return seconds >= 60
    ? `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
    : `${seconds.toFixed(1)}s`;
}

/**
 * What to say when there is nothing to play. Each status is a different situation and wants a
 * different next action from the viewer — telling them apart is the reason the API returns an
 * enum rather than an empty list.
 */
function emptyMessage(
  status: PlaylistRecordingCuts['status'],
  hasVersionCuts: boolean,
  detail?: string | null
): string | null {
  switch (status) {
    case 'blocked':
      // The only status whose text comes from the back end. The useful part is WHICH directory
      // is missing, which this side cannot know — and it is the one message here that names
      // something the reader is expected to go and do. Rendered in an Alert, which carries the
      // "not saved" heading, so the detail stands alone here rather than repeating it.
      return (
        detail ??
        'The recording cannot be saved to the share. It is kept safe meanwhile and appears here once that is fixed.'
      );
    case 'no_meeting':
      // Not a verdict on anything — the playlist simply has no meeting yet. Saying "not recorded"
      // here told someone who was about to record a meeting that their recording would not happen.
      return 'No meeting has run on this playlist yet. The recording appears here after one does.';
    case 'no_recording':
      return 'This meeting was not recorded. Tick "Record this meeting" when starting the bot if you want the video kept.';
    case 'pending':
      return 'The meeting is being recorded now. The video appears here once it ends.';
    case 'archiving':
      return 'The recording is being collected and verified. This usually takes a few seconds after the meeting ends.';
    case 'no_segments':
      return 'A recording exists, but nothing was transcribed against these versions, so there are no shots to jump to.';
    case 'ready':
      return hasVersionCuts
        ? null
        : 'This version was not discussed in the meeting recording.';
    default:
      return null;
  }
}

interface VirtualCutPlayerProps {
  data: PlaylistRecordingCuts | undefined;
  isLoading: boolean;
  error: Error | null;
  /** The version whose spans to play — normally whichever the review is showing. */
  versionId: number | null;
}

export function VirtualCutPlayer({
  data,
  isLoading,
  error,
  versionId,
}: VirtualCutPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  // A seek requested before the browser knows the duration is a silent no-op — see useVideoSeek,
  // which holds it and flushes on loadedmetadata.
  const { seekTo, onLoadedMetadata: handleLoadedMetadata } =
    useVideoSeek(videoRef);
  const [activeCut, setActiveCut] = useState(0);

  const cuts = useMemo(() => {
    if (!data || versionId == null) return [];
    return data.versions.find((v) => v.version_id === versionId)?.cuts ?? [];
  }, [data, versionId]);

  // Reset to the first span whenever the version changes: the clip indices belong to the version
  // being shown, and keeping "Clip 3" selected across a change would play an unrelated span.
  useEffect(() => {
    setActiveCut(0);
  }, [versionId, data?.media_url]);

  useEffect(() => {
    const cut = cuts[activeCut];
    if (cut) seekTo(cut.video_in_seconds);
  }, [cuts, activeCut, seekTo]);

  // Stop at the out-point. timeupdate fires roughly four times a second, so the check can overshoot
  // by ~250ms; clamping currentTime on the way out keeps repeated plays from drifting later each
  // time, which is what made the last frames of one shot bleed into the next.
  const handleTimeUpdate = useCallback(() => {
    const video = videoRef.current;
    const cut = cuts[activeCut];
    if (!video || !cut) return;
    if (video.currentTime >= cut.video_out_seconds) {
      video.pause();
      video.currentTime = cut.video_out_seconds;
    }
  }, [cuts, activeCut]);

  if (isLoading) return <Empty>Loading…</Empty>;
  if (error)
    return <Empty>Could not load the recording: {error.message}</Empty>;
  if (!data) return <Empty>No recording information for this playlist.</Empty>;

  const message = emptyMessage(data.status, cuts.length > 0, data.status_detail);
  if (message && data.status === 'blocked') {
    return (
      <Alert role="alert">
        <AlertHeading>This recording has not been saved</AlertHeading>
        {message}
      </Alert>
    );
  }
  if (message) return <Empty>{message}</Empty>;
  if (!data.media_url)
    return <Empty>The recording has no playable media yet.</Empty>;

  return (
    <Wrapper>
      <Video
        ref={videoRef}
        src={withBase(data.media_url)}
        controls
        preload="metadata"
        onLoadedMetadata={handleLoadedMetadata}
        onTimeUpdate={handleTimeUpdate}
      />

      {cuts.length > 1 && (
        <ClipRow>
          {cuts.map((cut, i) => (
            <ClipButton
              key={`${cut.video_in_seconds}-${i}`}
              $active={i === activeCut}
              onClick={() => setActiveCut(i)}
            >
              Clip {i + 1} · {formatSpan(cut)}
            </ClipButton>
          ))}
        </ClipRow>
      )}

      <Meta>
        {cuts.length} {cuts.length === 1 ? 'span' : 'spans'} of this meeting
        discussed this version
        {data.duration_seconds
          ? ` · recording is ${Math.round(data.duration_seconds)}s long`
          : ''}
      </Meta>
    </Wrapper>
  );
}
