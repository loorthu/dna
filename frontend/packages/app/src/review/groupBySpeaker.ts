import type { ReviewTranscriptLine } from '@dna/core';

export interface SpeakerTurn {
  speaker: string;
  startedAt: string | null;
  text: string;
}

/**
 * Merge consecutive lines from one speaker into a turn.
 *
 * Transcription arrives in short utterances, so one person speaking for twenty seconds produces a
 * dozen rows. Printing each with its own name and timestamp turns a conversation into a list;
 * merging the runs is what makes a transcript skimmable, which is the only way anyone reads one.
 *
 * A missing speaker breaks the run rather than joining it. Two unattributed utterances are not
 * evidence that one person said both, and merging them writes a paragraph nobody spoke.
 */
export function groupBySpeaker(lines: ReviewTranscriptLine[]): SpeakerTurn[] {
  const turns: SpeakerTurn[] = [];
  for (const line of lines) {
    const text = (line.text || '').trim();
    if (!text) continue;
    const speaker = line.speaker?.trim() || '';
    const last = turns[turns.length - 1];
    if (last && speaker && last.speaker === speaker) {
      last.text = `${last.text} ${text}`;
      continue;
    }
    turns.push({
      speaker: speaker || 'Unattributed',
      startedAt: line.absolute_start_time,
      text,
    });
  }
  return turns;
}
