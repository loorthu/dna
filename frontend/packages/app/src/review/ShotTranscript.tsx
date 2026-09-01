import styled from 'styled-components';
import type { ReviewTranscriptLine } from '@dna/core';
import { groupBySpeaker } from './groupBySpeaker';

/**
 * What was said about one shot, as a reader wants it rather than as it was captured — see
 * `groupBySpeaker` for why the utterances are merged before they are printed.
 */

const List = styled.div`
  display: flex;
  flex-direction: column;
  gap: 12px;
`;

const Turn = styled.div`
  display: flex;
  flex-direction: column;
  gap: 2px;
`;

const TurnHeader = styled.div`
  display: flex;
  align-items: baseline;
  gap: 8px;
`;

const Speaker = styled.span`
  font-size: 12px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.text.primary};
`;

const Time = styled.span`
  font-size: 11px;
  color: ${({ theme }) => theme.colors.text.muted};
`;

const Said = styled.p`
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: ${({ theme }) => theme.colors.text.secondary};
`;

const Empty = styled.div`
  padding: 4px 0 8px;
  font-size: 13px;
  color: ${({ theme }) => theme.colors.text.muted};
`;

function formatTime(iso: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

interface ShotTranscriptProps {
  lines: ReviewTranscriptLine[];
}

export function ShotTranscript({ lines }: ShotTranscriptProps) {
  const turns = groupBySpeaker(lines);
  if (turns.length === 0) {
    return <Empty>Nothing was transcribed against this shot.</Empty>;
  }
  return (
    <List>
      {turns.map((turn, i) => (
        <Turn key={`${turn.startedAt ?? i}-${i}`}>
          <TurnHeader>
            <Speaker>{turn.speaker}</Speaker>
            <Time>{formatTime(turn.startedAt)}</Time>
          </TurnHeader>
          <Said>{turn.text}</Said>
        </Turn>
      ))}
    </List>
  );
}
