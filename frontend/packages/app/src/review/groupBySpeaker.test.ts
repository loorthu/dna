import { describe, it, expect } from 'vitest';
import type { ReviewTranscriptLine } from '@dna/core';
import { groupBySpeaker } from './groupBySpeaker';

function line(
  speaker: string | null,
  text: string,
  at = '2026-08-30T18:00:00Z'
): ReviewTranscriptLine {
  return {
    speaker,
    text,
    absolute_start_time: at,
    start_time: null,
  };
}

describe('groupBySpeaker', () => {
  it('merges a run by one speaker into a paragraph', () => {
    const turns = groupBySpeaker([
      line('Jane', 'Push the haze back'),
      line('Jane', 'and soften the rim.'),
    ]);
    expect(turns).toHaveLength(1);
    expect(turns[0].text).toBe('Push the haze back and soften the rim.');
  });

  it('starts a new turn when the speaker changes', () => {
    const turns = groupBySpeaker([
      line('Jane', 'Push the haze back.'),
      line('Sam', 'Agreed.'),
      line('Jane', 'Thanks.'),
    ]);
    expect(turns.map((t) => t.speaker)).toEqual(['Jane', 'Sam', 'Jane']);
  });

  it('keeps the time the turn started, not the time it ended', () => {
    const turns = groupBySpeaker([
      line('Jane', 'First', '2026-08-30T18:00:00Z'),
      line('Jane', 'Second', '2026-08-30T18:00:09Z'),
    ]);
    expect(turns[0].startedAt).toBe('2026-08-30T18:00:00Z');
  });

  it('does not merge unattributed lines', () => {
    // Two lines with no speaker are not evidence that one person said both.
    const turns = groupBySpeaker([line(null, 'One'), line(null, 'Two')]);
    expect(turns).toHaveLength(2);
    expect(turns[0].speaker).toBe('Unattributed');
  });

  it('drops empty and whitespace-only utterances', () => {
    expect(groupBySpeaker([line('Jane', '   '), line('Jane', '')])).toEqual([]);
  });

  it('trims each utterance before joining, so runs do not double-space', () => {
    const turns = groupBySpeaker([
      line('Jane', '  Push the haze back  '),
      line('Jane', '  and soften it. '),
    ]);
    expect(turns[0].text).toBe('Push the haze back and soften it.');
  });
});
