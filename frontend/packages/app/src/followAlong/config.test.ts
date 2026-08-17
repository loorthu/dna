import { describe, it, expect } from 'vitest';
import { readFollowAlongConfig } from './config';

function env(values: Record<string, string | undefined>) {
  return values as unknown as ImportMetaEnv;
}

describe('readFollowAlongConfig', () => {
  it('reads broker, topic and session directory', () => {
    expect(
      readFollowAlongConfig(
        env({
          VITE_FOLLOW_ALONG_BROKER_URL: 'ws://broker.test:61614/stomp',
          VITE_FOLLOW_ALONG_TOPIC: '/topic/current_clip.xml',
          VITE_FOLLOW_ALONG_SESSIONS_URL: 'http://sessions.test:8080',
        })
      )
    ).toEqual({
      brokerURL: 'ws://broker.test:61614/stomp',
      topic: '/topic/current_clip.xml',
      sessionsUrl: 'http://sessions.test:8080',
    });
  });

  it('is off when nothing is configured', () => {
    expect(readFollowAlongConfig(env({}))).toBeNull();
  });

  it('is off without a broker URL', () => {
    expect(
      readFollowAlongConfig(
        env({ VITE_FOLLOW_ALONG_TOPIC: '/topic/current_clip.xml' })
      )
    ).toBeNull();
  });

  it('is off without a topic, since DNA ships knowing no default', () => {
    expect(
      readFollowAlongConfig(
        env({ VITE_FOLLOW_ALONG_BROKER_URL: 'ws://broker.test:61614/stomp' })
      )
    ).toBeNull();
  });

  it('treats blank values as unset', () => {
    expect(
      readFollowAlongConfig(
        env({
          VITE_FOLLOW_ALONG_BROKER_URL: '   ',
          VITE_FOLLOW_ALONG_TOPIC: '/topic/current_clip.xml',
        })
      )
    ).toBeNull();
  });

  it('works without a session directory', () => {
    expect(
      readFollowAlongConfig(
        env({
          VITE_FOLLOW_ALONG_BROKER_URL: 'ws://broker.test:61614/stomp',
          VITE_FOLLOW_ALONG_TOPIC: '/topic/current_clip.xml',
        })
      )
    ).toEqual({
      brokerURL: 'ws://broker.test:61614/stomp',
      topic: '/topic/current_clip.xml',
      sessionsUrl: '',
    });
  });

  it('trims surrounding whitespace', () => {
    expect(
      readFollowAlongConfig(
        env({
          VITE_FOLLOW_ALONG_BROKER_URL: ' ws://broker.test:61614/stomp ',
          VITE_FOLLOW_ALONG_TOPIC: ' /topic/current_clip.xml ',
        })
      )?.brokerURL
    ).toBe('ws://broker.test:61614/stomp');
  });
});
