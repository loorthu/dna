import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import userEvent from '@testing-library/user-event';
import { render, screen } from '../test/render';
import {
  ReviewSyncClient,
  createReviewSyncClient,
  type Version,
} from '@dna/core';
import { FollowAlongProvider, useFollowAlongContext } from '../contexts';
import { useFollowAlong } from './useFollowAlong';

const showToast = vi.fn();
vi.mock('../contexts/ToastContext', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../contexts/ToastContext')>();
  return {
    ...actual,
    useToast: () => ({ showToast, dismissToast: vi.fn() }),
  };
});

function version(id: number, externalRef?: string): Version {
  return {
    id,
    type: 'Version',
    name: `v${id}`,
    notes: [],
    ...(externalRef ? { external_ref: externalRef } : {}),
  };
}

const VERSIONS = [version(10, '100'), version(20, '200'), version(30)];

function clipXml(session: string, show: string, shot: string, jts: string) {
  return `<current_clip><session>${session}</session><show>${show}</show><shot>${shot}</shot><jts>${jts}</jts></current_clip>`;
}

function Harness({ versions = VERSIONS }: { versions?: Version[] }) {
  const { followedVersion, isOffPlaylist, enabled } = useFollowAlong({
    show: 'nite',
    playlistId: 7,
    versions,
  });
  const { session, setSession } = useFollowAlongContext();

  return (
    <div>
      <span data-testid="followed">{followedVersion?.name ?? 'none'}</span>
      <span data-testid="off-playlist">{String(isOffPlaylist)}</span>
      <span data-testid="enabled">{String(enabled)}</span>
      <span data-testid="session">{session ?? 'none'}</span>
      <button onClick={() => setSession('dailies')}>follow</button>
      <button onClick={() => setSession(null)}>unfollow</button>
    </div>
  );
}

describe('useFollowAlong', () => {
  let client: ReviewSyncClient;

  beforeEach(() => {
    localStorage.clear();
    showToast.mockClear();
    client = createReviewSyncClient({
      brokerURL: 'ws://broker.test:61614/stomp',
      topic: '/topic/current_clip.xml',
      // Report announcements straight away; settling is covered in @dna/core.
      settleMs: 0,
    });
  });

  afterEach(() => {
    client.disconnect();
  });

  function setup(versions?: Version[]) {
    return render(
      <FollowAlongProvider client={client}>
        <Harness versions={versions} />
      </FollowAlongProvider>
    );
  }

  async function follow(user: { click: (el: Element) => Promise<void> }) {
    await user.click(screen.getByRole('button', { name: 'follow' }));
  }

  function broadcast(xml: string) {
    act(() => {
      client.handleFrameBody(xml);
    });
  }

  it('follows nothing until a session is chosen', async () => {
    setup();

    expect(screen.getByTestId('enabled')).toHaveTextContent('false');
    broadcast(clipXml('dailies', 'nite', 'abc0100', '100'));
    expect(screen.getByTestId('followed')).toHaveTextContent('none');
  });

  it('resolves the broadcast clip onto the matching version', async () => {
    const user = userEvent.setup();
    setup();
    await follow(user);

    broadcast(clipXml('dailies', 'nite', 'abc0100', '200'));

    expect(screen.getByTestId('followed')).toHaveTextContent('v20');
    expect(screen.getByTestId('off-playlist')).toHaveTextContent('false');
    expect(screen.getByTestId('enabled')).toHaveTextContent('true');
  });

  it('reports off-playlist when no version carries the ref', async () => {
    const user = userEvent.setup();
    setup();
    await follow(user);

    broadcast(clipXml('dailies', 'nite', 'zzz9999', '999'));

    expect(screen.getByTestId('followed')).toHaveTextContent('none');
    expect(screen.getByTestId('off-playlist')).toHaveTextContent('true');
  });

  it('warns once per clip, not once per broadcast', async () => {
    const user = userEvent.setup();
    setup();
    await follow(user);

    broadcast(clipXml('dailies', 'nite', 'zzz9999', '999'));
    broadcast(clipXml('dailies', 'nite', 'zzz9999', '999'));
    broadcast(clipXml('dailies', 'nite', 'zzz9999', '999'));

    expect(showToast).toHaveBeenCalledTimes(1);
    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'warning' })
    );
  });

  it('warns again for a different off-playlist clip', async () => {
    const user = userEvent.setup();
    setup();
    await follow(user);

    broadcast(clipXml('dailies', 'nite', 'zzz9999', '998'));
    broadcast(clipXml('dailies', 'nite', 'zzz9998', '999'));

    expect(showToast).toHaveBeenCalledTimes(2);
  });

  it('does not warn for a clip that is in the playlist', async () => {
    const user = userEvent.setup();
    setup();
    await follow(user);

    broadcast(clipXml('dailies', 'nite', 'abc0100', '100'));

    expect(showToast).not.toHaveBeenCalled();
  });

  it('ignores broadcasts from another session', async () => {
    const user = userEvent.setup();
    setup();
    await follow(user);

    broadcast(clipXml('fx_review', 'nite', 'abc0100', '100'));

    expect(screen.getByTestId('followed')).toHaveTextContent('none');
    expect(showToast).not.toHaveBeenCalled();
  });

  it('ignores broadcasts for another show', async () => {
    const user = userEvent.setup();
    setup();
    await follow(user);

    broadcast(clipXml('dailies', 'kpop', 'abc0100', '100'));

    expect(screen.getByTestId('followed')).toHaveTextContent('none');
  });

  it('drops the followed version when the user stops following', async () => {
    const user = userEvent.setup();
    setup();
    await follow(user);
    broadcast(clipXml('dailies', 'nite', 'abc0100', '100'));
    expect(screen.getByTestId('followed')).toHaveTextContent('v10');

    await user.click(screen.getByRole('button', { name: 'unfollow' }));

    expect(screen.getByTestId('followed')).toHaveTextContent('none');
    expect(screen.getByTestId('enabled')).toHaveTextContent('false');
  });

  it('persists the chosen session per playlist', async () => {
    const user = userEvent.setup();
    const { unmount } = setup();
    await follow(user);
    expect(localStorage.getItem('dna-follow-along-session:7')).toBe('dailies');

    unmount();
    setup();

    expect(screen.getByTestId('session')).toHaveTextContent('dailies');
  });
});
