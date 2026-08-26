import { describe, it, expect } from 'vitest';
import type { BotSession, BotStatusEventPayload } from '@dna/core';
import { nextSessionForStatusEvent, parseMeetingUrl } from './useTranscription';

const PLAYLIST_ID = 461876;

function liveSession(overrides: Partial<BotSession> = {}): BotSession {
  return {
    platform: 'google_meet',
    meeting_id: 'duv-anrv-ztp',
    playlist_id: PLAYLIST_ID,
    status: 'in_call',
    created_at: '2026-08-26T03:45:00.000Z',
    updated_at: '2026-08-26T03:45:00.000Z',
    ...overrides,
  };
}

function frame(
  overrides: Partial<BotStatusEventPayload> = {}
): BotStatusEventPayload {
  return {
    platform: 'google_meet',
    meeting_id: 'duv-anrv-ztp',
    playlist_id: PLAYLIST_ID,
    ...overrides,
  };
}

describe('nextSessionForStatusEvent', () => {
  it('advances the status of a session it has', () => {
    const next = nextSessionForStatusEvent(
      liveSession({ status: 'joining' }),
      frame({ status: 'in_call' }),
      PLAYLIST_ID
    );

    expect(next?.status).toBe('in_call');
  });

  // The regression. The backend publishes this exact frame from the segment-discard warning, and
  // taking its missing status as the new one made a live bot read as idle — which is what removed
  // the Stop button mid-meeting on 2026-08-26.
  it('leaves the status alone when the frame carries none', () => {
    const next = nextSessionForStatusEvent(
      liveSession({ status: 'transcribing' }),
      frame({ saving_segments: false, warnings: ['no_version_in_review'] }),
      PLAYLIST_ID
    );

    expect(next?.status).toBe('transcribing');
    expect(next?.saving_segments).toBe(false);
    expect(next?.warnings).toEqual(['no_version_in_review']);
  });

  it('keeps advisory fields it already had when a later frame omits them', () => {
    const next = nextSessionForStatusEvent(
      liveSession({
        saving_segments: false,
        warnings: ['no_version_in_review'],
      }),
      frame({ status: 'transcribing' }),
      PLAYLIST_ID
    );

    expect(next?.saving_segments).toBe(false);
    expect(next?.warnings).toEqual(['no_version_in_review']);
  });

  it('starts a session from an active frame when there is none', () => {
    const next = nextSessionForStatusEvent(
      null,
      frame({ status: 'waiting_room' }),
      PLAYLIST_ID
    );

    expect(next).toMatchObject({
      platform: 'google_meet',
      meeting_id: 'duv-anrv-ztp',
      playlist_id: PLAYLIST_ID,
      status: 'waiting_room',
    });
  });

  it('does not start a session from a terminal frame', () => {
    expect(
      nextSessionForStatusEvent(
        null,
        frame({ status: 'completed' }),
        PLAYLIST_ID
      )
    ).toBeNull();
  });

  // An advisory frame has no status to judge. Starting a session from one would put a Stop button
  // in front of a bot that may already have left.
  it('does not start a session from an advisory frame', () => {
    expect(
      nextSessionForStatusEvent(
        null,
        frame({ saving_segments: false }),
        PLAYLIST_ID
      )
    ).toBeNull();
  });

  it('falls back to the open playlist when the frame names none', () => {
    const next = nextSessionForStatusEvent(
      null,
      frame({ status: 'in_call', playlist_id: undefined }),
      PLAYLIST_ID
    );

    expect(next?.playlist_id).toBe(PLAYLIST_ID);
  });
});

describe('parseMeetingUrl', () => {
  it.each([
    ['https://meet.google.com/duv-anrv-ztp', 'duv-anrv-ztp'],
    ['https://meet.google.com/DUV-ANRV-ZTP?authuser=0', 'duv-anrv-ztp'],
    ['duv-anrv-ztp', 'duv-anrv-ztp'],
  ])('reads %s as a Meet code', (url, expected) => {
    expect(parseMeetingUrl(url)).toEqual({
      platform: 'google_meet',
      meetingId: expected,
    });
  });

  it('rejects something that is not a meeting', () => {
    expect(parseMeetingUrl('https://example.com/hello')).toBeNull();
  });
});
