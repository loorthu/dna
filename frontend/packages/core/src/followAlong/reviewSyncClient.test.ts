// @vitest-environment jsdom

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ReviewSyncClient, createReviewSyncClient } from './reviewSyncClient';
import type { ReviewFocus } from './types';

function clipXml(
  session: string,
  show: string,
  shot: string,
  jts: string,
  guid = ''
) {
  const guidElement = guid ? `<guid>${guid}</guid>` : '';
  return `<current_clip><session>${session}</session><show>${show}</show><shot>${shot}</shot>${guidElement}<jts>${jts}</jts></current_clip>`;
}

describe('ReviewSyncClient', () => {
  let client: ReviewSyncClient;
  let focuses: ReviewFocus[];

  beforeEach(() => {
    // Settling is exercised separately; these cover filtering, so report
    // straight away and keep the expectations about what got through.
    client = createReviewSyncClient({
      brokerURL: 'ws://broker.test:61614/stomp',
      topic: '/topic/current_clip.xml',
      settleMs: 0,
    });
    focuses = [];
    client.subscribe((focus) => focuses.push(focus));
  });

  it('notifies subscribers for the selected session', () => {
    client.setSession('director_review');
    client.handleFrameBody(clipXml('director_review', 'nite', 'abc0100', '42'));

    expect(focuses).toEqual([
      {
        session: 'director_review',
        show: 'nite',
        shot: 'abc0100',
        externalRef: '42',
        clipRef: '',
      },
    ]);
  });

  it('ignores messages from a different session', () => {
    client.setSession('director_review');
    client.handleFrameBody(clipXml('fx_review', 'nite', 'abc0100', '42'));

    expect(focuses).toEqual([]);
    expect(client.lastFocus).toBeNull();
  });

  it('ignores every message until a session is selected', () => {
    client.handleFrameBody(clipXml('director_review', 'nite', 'abc0100', '42'));

    expect(focuses).toEqual([]);
  });

  it('ignores messages for a different show on the same session name', () => {
    client.setSession('dailies');
    client.setShow('nite');
    client.handleFrameBody(clipXml('dailies', 'kpop', 'abc0100', '42'));

    expect(focuses).toEqual([]);
  });

  it('matches session and show case-insensitively', () => {
    client.setSession('Director_Review');
    client.setShow('NITE');
    client.handleFrameBody(clipXml('director_review', 'nite', 'abc0100', '42'));

    expect(focuses).toHaveLength(1);
  });

  it('does not filter on show when no show is set', () => {
    client.setSession('dailies');
    client.handleFrameBody(clipXml('dailies', 'kpop', 'abc0100', '42'));

    expect(focuses).toHaveLength(1);
  });

  it('ignores unparseable payloads', () => {
    client.setSession('dailies');
    client.handleFrameBody('<current_clip><jts>42');
    client.handleFrameBody('');

    expect(focuses).toEqual([]);
  });

  it('records the last matching focus', () => {
    client.setSession('dailies');
    client.handleFrameBody(clipXml('dailies', 'nite', 'abc0100', '1'));
    client.handleFrameBody(clipXml('dailies', 'nite', 'abc0200', '2'));

    expect(client.lastFocus?.externalRef).toBe('2');
  });

  it('clears the last focus when the session changes', () => {
    client.setSession('dailies');
    client.handleFrameBody(clipXml('dailies', 'nite', 'abc0100', '1'));
    client.setSession('fx_review');

    expect(client.lastFocus).toBeNull();
    expect(client.session).toBe('fx_review');
  });

  it('keeps the last focus when the session is set to the same name', () => {
    client.setSession('dailies');
    client.handleFrameBody(clipXml('dailies', 'nite', 'abc0100', '1'));
    client.setSession('dailies');

    expect(client.lastFocus?.externalRef).toBe('1');
  });

  it('stops notifying after unsubscribe', () => {
    const seen: ReviewFocus[] = [];
    const unsubscribe = client.subscribe((focus) => seen.push(focus));
    client.setSession('dailies');
    unsubscribe();
    client.handleFrameBody(clipXml('dailies', 'nite', 'abc0100', '1'));

    expect(seen).toEqual([]);
    expect(focuses).toHaveLength(1);
  });

  it('keeps notifying other subscribers when one throws', () => {
    client.subscribe(() => {
      throw new Error('boom');
    });
    const later: ReviewFocus[] = [];
    client.subscribe((focus) => later.push(focus));
    vi.spyOn(console, 'error').mockImplementation(() => {});

    client.setSession('dailies');
    client.handleFrameBody(clipXml('dailies', 'nite', 'abc0100', '1'));

    expect(later).toHaveLength(1);
  });

  it('uses a supplied parser instead of the default', () => {
    const custom = createReviewSyncClient({
      brokerURL: 'ws://broker.test:61614/stomp',
      topic: '/topic/current_clip.json',
      parse: (body) => JSON.parse(body) as ReviewFocus,
      settleMs: 0,
    });
    const seen: ReviewFocus[] = [];
    custom.subscribe((focus) => seen.push(focus));
    custom.setSession('dailies');

    custom.handleFrameBody(
      JSON.stringify({
        session: 'dailies',
        show: 'nite',
        shot: 'abc0100',
        externalRef: 'zz9',
      })
    );

    expect(seen[0]?.externalRef).toBe('zz9');
  });

  it('starts disconnected with no error', () => {
    expect(client.isConnected).toBe(false);
    expect(client.connectionError).toBeNull();
  });
});

// The player rebroadcasts continuously and more than one publisher can announce
// under one session name, so announcements arrive in bursts. Settling reports
// where a burst landed rather than every step through it.
describe('ReviewSyncClient settling', () => {
  let client: ReviewSyncClient;
  let focuses: ReviewFocus[];

  beforeEach(() => {
    vi.useFakeTimers();
    client = createReviewSyncClient({
      brokerURL: 'ws://broker.test:61614/stomp',
      topic: '/topic/current_clip.xml',
      settleMs: 1500,
    });
    focuses = [];
    client.subscribe((focus) => focuses.push(focus));
    client.setSession('rounds');
    client.setShow('ccf');
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('reports a clip once it has settled', () => {
    client.handleFrameBody(clipXml('rounds', 'ccf', 'taf0140', '191004'));
    expect(focuses).toEqual([]);

    vi.advanceTimersByTime(1500);

    expect(focuses.map((f) => f.externalRef)).toEqual(['191004']);
  });

  it('reports only where a burst landed', () => {
    client.handleFrameBody(clipXml('rounds', 'ccf', 'a', '1'));
    client.handleFrameBody(clipXml('rounds', 'ccf', 'b', '2'));
    client.handleFrameBody(clipXml('rounds', 'ccf', 'c', '3'));

    vi.advanceTimersByTime(1500);

    expect(focuses.map((f) => f.externalRef)).toEqual(['3']);
  });

  it('ignores the player repeating the clip it is already reporting', () => {
    client.handleFrameBody(clipXml('rounds', 'ccf', 'taf0140', '191004'));
    vi.advanceTimersByTime(1500);

    client.handleFrameBody(clipXml('rounds', 'ccf', 'taf0140', '191004'));
    client.handleFrameBody(clipXml('rounds', 'ccf', 'taf0140', '191004'));
    vi.advanceTimersByTime(5000);

    expect(focuses).toHaveLength(1);
  });

  it('reports a genuine change after the first has settled', () => {
    client.handleFrameBody(clipXml('rounds', 'ccf', 'taf0140', '191004'));
    vi.advanceTimersByTime(1500);
    client.handleFrameBody(clipXml('rounds', 'ccf', 'taf0150', '192358'));
    vi.advanceTimersByTime(1500);

    expect(focuses.map((f) => f.externalRef)).toEqual(['191004', '192358']);
  });

  it('treats the same version announced as a different clip as no change', () => {
    client.handleFrameBody(clipXml('rounds', 'ccf', 'taf0140', '191004', 'c1'));
    vi.advanceTimersByTime(1500);
    client.handleFrameBody(clipXml('rounds', 'ccf', 'taf0140', '191004', 'c2'));
    vi.advanceTimersByTime(1500);

    expect(focuses).toHaveLength(1);
  });

  it('drops a pending announcement when the session changes', () => {
    client.handleFrameBody(clipXml('rounds', 'ccf', 'taf0140', '191004'));
    client.setSession('director');
    vi.advanceTimersByTime(5000);

    expect(focuses).toEqual([]);
  });

  it('reports immediately when settling is switched off', () => {
    const instant = createReviewSyncClient({
      brokerURL: 'ws://broker.test:61614/stomp',
      topic: '/topic/current_clip.xml',
      settleMs: 0,
    });
    const seen: ReviewFocus[] = [];
    instant.subscribe((focus) => seen.push(focus));
    instant.setSession('rounds');

    instant.handleFrameBody(clipXml('rounds', 'ccf', 'taf0140', '191004'));

    expect(seen.map((f) => f.externalRef)).toEqual(['191004']);
  });
});
