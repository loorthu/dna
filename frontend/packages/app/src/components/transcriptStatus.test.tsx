import { describe, it, expect } from 'vitest';
import { transcriptStatus } from './transcriptStatus';

describe('transcriptStatus', () => {
  it('does not claim a connection when no bot is in the meeting', () => {
    // The regression this exists for: the app's event socket is up from page load, so an empty
    // transcript announced "Connected - waiting for transcript" on a playlist no bot had ever
    // been dispatched to — a promise that words were on their way with nothing listening.
    const { tone, label } = transcriptStatus(false, true, 0);

    expect(label).toBe('No bot in this meeting');
    expect(tone).toBe('idle');
  });

  it('waits for the transcript only while a bot is actually live', () => {
    expect(transcriptStatus(true, true, 0)).toEqual({
      tone: 'live',
      label: 'Connected - waiting for transcript',
    });
  });

  it('reports a lost socket only when there is a meeting to lose it from', () => {
    // With a live bot the socket is the difference between hearing the meeting and missing it.
    expect(transcriptStatus(true, false, 4).label).toBe(
      'Reconnecting... • 4 segments'
    );
    // With no bot it qualifies nothing, so it is not mentioned at all.
    expect(transcriptStatus(false, false, 4).label).toBe('4 segments');
  });

  it('keeps naming segments already in hand after the bot leaves', () => {
    // They are a record of a meeting that happened; they do not stop being real once it ends.
    expect(transcriptStatus(false, true, 12)).toEqual({
      tone: 'idle',
      label: '12 segments',
    });
    expect(transcriptStatus(true, true, 12).label).toBe('Live • 12 segments');
  });

  it('counts one segment in the singular', () => {
    expect(transcriptStatus(false, true, 1).label).toBe('1 segment');
  });
});
