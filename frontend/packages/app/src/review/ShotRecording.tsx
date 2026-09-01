import { useEffect, useRef, useState } from 'react';
import styled from 'styled-components';
import type { ReviewCut, ReviewRecording } from '@dna/core';
import { useVideoSeek } from '../hooks/useVideoSeek';
import { formatClock, recordingMessage } from './recordingMessage';

/**
 * The meeting recording, opened at the point this shot was discussed.
 *
 * Unlike the coordinator's cut player this does NOT stop at the span's out-point. An artist who
 * followed a link to their shot is watching to find out what was decided, and the sentence that
 * finishes the thought is frequently the one after the last segment filed against them. The spans
 * are offered as places to jump to, not as a fence.
 *
 * The <video> is mounted only when the section is open, which is what keeps a thirty-shot page
 * from asking nginx for the same recording thirty times on load.
 */

const Wrapper = styled.div`
  display: flex;
  flex-direction: column;
  gap: 10px;
`;

const Video = styled.video`
  width: 100%;
  max-height: 50vh;
  background: #000;
  border-radius: ${({ theme }) => theme.radii.md};
`;

const SpanRow = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
`;

const SpanButton = styled.button<{ $active: boolean }>`
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

const Meta = styled.div`
  font-size: 11px;
  color: ${({ theme }) => theme.colors.text.muted};
`;

const Empty = styled.div`
  padding: 8px 0 12px;
  font-size: 13px;
  line-height: 1.5;
  color: ${({ theme }) => theme.colors.text.muted};
`;

interface ShotRecordingProps {
  recording: ReviewRecording;
  cuts: ReviewCut[];
}

export function ShotRecording({ recording, cuts }: ShotRecordingProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const { seekTo, onLoadedMetadata } = useVideoSeek(videoRef);
  const [activeSpan, setActiveSpan] = useState(0);

  useEffect(() => {
    const cut = cuts[activeSpan];
    if (cut) seekTo(cut.video_in_seconds);
  }, [cuts, activeSpan, seekTo]);

  const message = recordingMessage(recording.status, cuts.length > 0);
  if (message) return <Empty>{message}</Empty>;
  if (!recording.media_url)
    return <Empty>The recording has no playable media yet.</Empty>;

  return (
    <Wrapper>
      <Video
        ref={videoRef}
        src={recording.media_url}
        controls
        preload="metadata"
        onLoadedMetadata={onLoadedMetadata}
      />

      {cuts.length > 1 && (
        <SpanRow>
          {cuts.map((cut, i) => (
            <SpanButton
              key={`${cut.video_in_seconds}-${i}`}
              $active={i === activeSpan}
              onClick={() => setActiveSpan(i)}
            >
              {formatClock(cut.video_in_seconds)}
            </SpanButton>
          ))}
        </SpanRow>
      )}

      <Meta>
        {cuts.length === 1
          ? `Your shot comes up at ${formatClock(cuts[0].video_in_seconds)}`
          : `Discussed in ${cuts.length} places`}
        {recording.duration_seconds
          ? ` · the meeting ran ${formatClock(recording.duration_seconds)}`
          : ''}
        . Playback is not limited to your shot — keep watching for anything said
        after it.
      </Meta>
    </Wrapper>
  );
}
