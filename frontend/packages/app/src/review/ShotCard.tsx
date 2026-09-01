import styled from 'styled-components';
import { ExternalLink } from 'lucide-react';
import type { ReviewRecording, ReviewShot } from '@dna/core';
import { ExpandableSection } from '../components/ExpandableSection';
import { ShotTranscript } from './ShotTranscript';
import { ShotRecording } from './ShotRecording';

/**
 * One shot, and everything the review said about it.
 *
 * Notes are always open, because they are what the artist came for and what the email already
 * showed them. The transcript and the recording are folded away: a page of thirty shots with
 * every transcript expanded is unreadable, and thirty mounted <video> elements would each ask
 * nginx for the same recording. The shot that was linked to is the exception — it opens both,
 * since the reader arrived asking about that one.
 */

const Card = styled.section<{ $highlighted: boolean }>`
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 20px;
  border-radius: ${({ theme }) => theme.radii.lg};
  background: ${({ theme }) => theme.colors.bg.elevated};
  border: 1px solid
    ${({ theme, $highlighted }) =>
      $highlighted ? theme.colors.accent.main : theme.colors.border.subtle};
  /* The heading is sticky, so an anchored jump has to stop short of it or the shot it landed on
     is the one hidden behind the bar. */
  scroll-margin-top: 96px;
`;

const Head = styled.div`
  display: flex;
  gap: 16px;
  align-items: flex-start;
`;

const Index = styled.div`
  flex: 0 0 auto;
  width: 28px;
  font-family: ${({ theme }) => theme.fonts.mono};
  font-size: 13px;
  color: ${({ theme }) => theme.colors.text.muted};
  padding-top: 2px;
`;

const Thumbnail = styled.img`
  flex: 0 0 auto;
  width: 128px;
  height: 72px;
  object-fit: cover;
  border-radius: ${({ theme }) => theme.radii.sm};
  background: ${({ theme }) => theme.colors.bg.surface};
`;

const ThumbnailPlaceholder = styled.div`
  flex: 0 0 auto;
  width: 128px;
  height: 72px;
  border-radius: ${({ theme }) => theme.radii.sm};
  background: ${({ theme }) => theme.colors.bg.surface};
`;

const Identity = styled.div`
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
`;

const Name = styled.h2`
  margin: 0;
  font-family: ${({ theme }) => theme.fonts.sans};
  font-size: 16px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.text.primary};
  word-break: break-word;
`;

const NameLink = styled.a`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: inherit;
  text-decoration: none;

  &:hover {
    color: ${({ theme }) => theme.colors.accent.main};
  }
`;

const Facts = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: ${({ theme }) => theme.colors.text.secondary};
`;

const Separator = styled.span`
  color: ${({ theme }) => theme.colors.text.muted};
`;

const StatusPill = styled.span`
  padding: 2px 8px;
  border-radius: 999px;
  font-family: ${({ theme }) => theme.fonts.mono};
  font-size: 11px;
  text-transform: uppercase;
  color: ${({ theme }) => theme.colors.text.secondary};
  background: ${({ theme }) => theme.colors.bg.surface};
  border: 1px solid ${({ theme }) => theme.colors.border.subtle};
`;

const FilePath = styled.div`
  font-family: ${({ theme }) => theme.fonts.mono};
  font-size: 11px;
  color: ${({ theme }) => theme.colors.text.muted};
  word-break: break-all;
`;

const Notes = styled.div`
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px 16px;
  border-radius: ${({ theme }) => theme.radii.md};
  background: ${({ theme }) => theme.colors.bg.surface};
`;

const Note = styled.div`
  display: flex;
  flex-direction: column;
  gap: 4px;
`;

const Byline = styled.div`
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.text.primary};
`;

const Pending = styled.span`
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: ${({ theme }) => theme.colors.status.warning};
`;

const NoteSubject = styled.div`
  font-size: 13px;
  font-weight: 500;
  color: ${({ theme }) => theme.colors.text.secondary};
`;

/* Rendered as written, not as markup. The notes email prints the same text the same way, and a
   note that reads one way in the mail and another on the page it links to is worse than plain. */
const NoteBody = styled.p`
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  color: ${({ theme }) => theme.colors.text.secondary};
`;

const NoNotes = styled.div`
  font-size: 13px;
  font-style: italic;
  color: ${({ theme }) => theme.colors.text.muted};
`;

const Sections = styled.div`
  display: flex;
  flex-direction: column;
  border-top: 1px solid ${({ theme }) => theme.colors.border.subtle};
  padding-top: 4px;
`;

interface ShotCardProps {
  shot: ReviewShot;
  recording: ReviewRecording;
  /** True for the shot the link pointed at — it opens its transcript and recording. */
  highlighted: boolean;
  statusLabel: string;
}

export function ShotCard({
  shot,
  recording,
  highlighted,
  statusLabel,
}: ShotCardProps) {
  const facts = [shot.artist_name, shot.entity_name, shot.task_name].filter(
    Boolean
  );

  return (
    <Card id={shot.anchor} $highlighted={highlighted}>
      <Head>
        <Index>{shot.index}</Index>
        {shot.thumbnail ? (
          <Thumbnail src={shot.thumbnail} alt="" loading="lazy" />
        ) : (
          <ThumbnailPlaceholder />
        )}
        <Identity>
          <Name>
            {shot.prodtrack_detail_url ? (
              <NameLink
                href={shot.prodtrack_detail_url}
                target="_blank"
                rel="noreferrer"
              >
                {shot.name}
                <ExternalLink size={14} />
              </NameLink>
            ) : (
              shot.name
            )}
          </Name>
          <Facts>
            {facts.map((fact, i) => (
              <span key={fact}>
                {i > 0 && <Separator>· </Separator>}
                {fact}
              </span>
            ))}
            {statusLabel && <StatusPill>{statusLabel}</StatusPill>}
          </Facts>
          {shot.frame_path && <FilePath>{shot.frame_path}</FilePath>}
        </Identity>
      </Head>

      <Notes>
        {shot.notes.length === 0 ? (
          <NoNotes>No notes were written on this shot.</NoNotes>
        ) : (
          shot.notes.map((note, i) => (
            <Note key={`${note.author_email}-${i}`}>
              <Byline>
                {note.author_name}
                {/* Said plainly rather than hidden: an artist reading a note that has not reached
                    the tracker yet should know it may still change. */}
                {!note.published && <Pending>not yet published</Pending>}
              </Byline>
              {note.subject && <NoteSubject>{note.subject}</NoteSubject>}
              {note.content && <NoteBody>{note.content}</NoteBody>}
            </Note>
          ))
        )}
      </Notes>

      <Sections>
        <ExpandableSection
          title={
            shot.transcript.length > 0
              ? `Transcript (${shot.transcript.length} lines)`
              : 'Transcript'
          }
          defaultOpen={highlighted}
        >
          <ShotTranscript lines={shot.transcript} />
        </ExpandableSection>
        <ExpandableSection
          title={
            shot.cuts.length > 0
              ? `Recording (${shot.cuts.length} ${
                  shot.cuts.length === 1 ? 'span' : 'spans'
                })`
              : 'Recording'
          }
          defaultOpen={highlighted}
        >
          <ShotRecording recording={recording} cuts={shot.cuts} />
        </ExpandableSection>
      </Sections>
    </Card>
  );
}
