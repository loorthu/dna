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
