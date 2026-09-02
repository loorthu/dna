import { describe, it, expect } from 'vitest';
import { formatClock, recordingMessage } from './recordingMessage';

/**
 * Every one of these statuses renders as an empty box if it is not distinguished, and an empty
 * box is indistinguishable from a bug. What is asserted here is that each says something
 * different, and that a playable recording says nothing at all.
 */
describe('recordingMessage', () => {
  it('says nothing when there is a recording and spans to play', () => {
    expect(recordingMessage('ready', true)).toBeNull();
  });

  it('distinguishes a shot nobody discussed from a meeting nobody recorded', () => {
    expect(recordingMessage('ready', false)).not.toBe(
      recordingMessage('no_recording', false)
    );
    expect(recordingMessage('ready', false)).toBeTruthy();
  });

  it('gives each state its own answer', () => {
    const statuses = [
      'disabled',
      'no_meeting',
      'no_recording',
      'pending',
      'archiving',
      'blocked',
      'no_segments',
    ] as const;
    const messages = statuses.map((s) => recordingMessage(s, false));
    expect(messages.every(Boolean)).toBe(true);
    expect(new Set(messages).size).toBe(statuses.length);
  });

  it('tells the reader when to come back for one still being made', () => {
    expect(recordingMessage('pending', false)).toMatch(/once it ends/);
    expect(recordingMessage('archiving', false)).toMatch(/minute/);
  });

  it('does not hand the artist an instruction only an admin can follow', () => {
    // The coordinator's player names the directory to create. Here that would read as a job for
    // someone who has never seen the share — so this says the video is safe and coming, and
    // stops there.
    const message = recordingMessage('blocked', false) ?? '';
    expect(message).toMatch(/safe/);
    expect(message).not.toMatch(/lib\.recording|directory|share root/);
  });
});

describe('formatClock', () => {
  it.each([
    [0, '0:00'],
    [9, '0:09'],
    [61, '1:01'],
    [600, '10:00'],
    [3599, '59:59'],
  ])('renders %d seconds as %s', (seconds, expected) => {
    expect(formatClock(seconds)).toBe(expected);
  });

  it('never renders a negative clock', () => {
    expect(formatClock(-5)).toBe('0:00');
  });
});
