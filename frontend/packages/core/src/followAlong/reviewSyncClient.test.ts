// @vitest-environment jsdom

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ReviewSyncClient, createReviewSyncClient } from './reviewSyncClient';
import type { ReviewFocus } from './types';

function clipXml(session: string, show: string, shot: string, jts: string) {
  return `<current_clip><session>${session}</session><show>${show}</show><shot>${shot}</shot><jts>${jts}</jts></current_clip>`;
}

describe('ReviewSyncClient', () => {
  let client: ReviewSyncClient;
  let focuses: ReviewFocus[];

  beforeEach(() => {
    client = createReviewSyncClient({
      brokerURL: 'ws://broker.test:61614/stomp',
      topic: '/topic/current_clip.xml',
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
