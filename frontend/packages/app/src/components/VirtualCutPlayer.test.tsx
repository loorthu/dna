import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '../test/render';
import { VirtualCutPlayer } from './VirtualCutPlayer';
import type {
  PlaylistRecordingCuts,
  RecordingCutsStatus,
  RecordingCut,
} from '@dna/core';

/**
 * jsdom does not implement playback: `pause()` throws "Not implemented", and `currentTime` is
 * inert. The whole player is expressed in those two, so the element is stubbed with a model of
 * what the real DOM does — writes to `currentTime` are recorded, and `readyState` decides whether
 * a write takes at all. Stubbing them as no-ops would leave every assertion here vacuous.
 */
let readyState = 0;
let currentTime = 0;
const pause = vi.fn();

const originalReadyState = Object.getOwnPropertyDescriptor(
  HTMLMediaElement.prototype,
  'readyState'
);
const originalCurrentTime = Object.getOwnPropertyDescriptor(
  HTMLMediaElement.prototype,
  'currentTime'
);
const originalPause = HTMLMediaElement.prototype.pause;

beforeEach(() => {
  readyState = 0;
  currentTime = 0;
  pause.mockClear();

  Object.defineProperty(HTMLMediaElement.prototype, 'readyState', {
    configurable: true,
    get: () => readyState,
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'currentTime', {
    configurable: true,
    get: () => currentTime,
    set: (value: number) => {
      currentTime = value;
    },
  });
  HTMLMediaElement.prototype.pause = pause;
});

afterEach(() => {
  if (originalReadyState) {
    Object.defineProperty(
      HTMLMediaElement.prototype,
      'readyState',
      originalReadyState
    );
  }
  if (originalCurrentTime) {
    Object.defineProperty(
      HTMLMediaElement.prototype,
      'currentTime',
      originalCurrentTime
    );
  }
  HTMLMediaElement.prototype.pause = originalPause;
});

const VERSION_ID = 5712082;

function cut(inSeconds: number, outSeconds: number): RecordingCut {
  return {
    video_in_seconds: inSeconds,
    video_out_seconds: outSeconds,
    transcript_segment_ids: [`ch-0:1:${inSeconds}`],
  };
}

function ready(cuts: RecordingCut[]): PlaylistRecordingCuts {
  return {
    playlist_id: 461876,
    status: 'ready',
    status_detail: null,
    media_url:
      '/recordings/nite/lib.recording/pix/ref/dna/20260826/NITE_Director_Review_2026_08_25_20_49_PDT_Recording.mp4',
    duration_seconds: 250,
    recording_t0: '2026-08-26T03:49:02.593Z',
    recording_t0_source: 'vexa_recorder_clock',
    versions: [{ version_id: VERSION_ID, body_hash: 'd92e8286', cuts }],
  };
}

function empty(
  status: RecordingCutsStatus,
  statusDetail: string | null = null
): PlaylistRecordingCuts {
  return {
    playlist_id: 461876,
    status,
    status_detail: statusDetail,
    media_url: null,
    duration_seconds: null,
    recording_t0: null,
    recording_t0_source: null,
    versions: [],
  };
}

function renderPlayer(
  data: PlaylistRecordingCuts | undefined,
  versionId: number | null = VERSION_ID
) {
  return render(
    <VirtualCutPlayer
      data={data}
      isLoading={false}
      error={null}
      versionId={versionId}
    />
  );
}

function video(): HTMLVideoElement {
  const element = document.querySelector('video');
  if (!element) throw new Error('no <video> rendered');
  return element as HTMLVideoElement;
}

describe('VirtualCutPlayer seeking', () => {
  it('seeks straight to the in-point when the duration is already known', () => {
    readyState = 1;

    renderPlayer(ready([cut(61.155, 62.179)]));

    expect(currentTime).toBe(61.155);
  });

  // Setting currentTime before loadedmetadata is a silent no-op in a real browser: the write is
  // dropped, no error is raised, and the clip plays from the start of the meeting.
  it('holds the seek until the duration is known, then flushes it', () => {
    renderPlayer(ready([cut(61.155, 62.179)]));

    expect(currentTime).toBe(0);

    readyState = 1;
    fireEvent(video(), new Event('loadedmetadata'));

    expect(currentTime).toBe(61.155);
  });
});

describe('VirtualCutPlayer stopping at the out-point', () => {
  it('pauses and clamps once play reaches the out-point', () => {
    readyState = 1;
    renderPlayer(ready([cut(10, 20)]));

    // timeupdate fires roughly four times a second, so the browser reports a time PAST the
    // out-point rather than exactly on it.
    currentTime = 20.24;
    fireEvent.timeUpdate(video());

    expect(pause).toHaveBeenCalled();
    // Clamped, not left where the overshoot landed: without this, each replay starts a little
    // later than the last and the end of one shot bleeds into the next.
    expect(currentTime).toBe(20);
  });

  it('leaves play alone before the out-point', () => {
    readyState = 1;
    renderPlayer(ready([cut(10, 20)]));

    currentTime = 15;
    fireEvent.timeUpdate(video());

    expect(pause).not.toHaveBeenCalled();
    expect(currentTime).toBe(15);
  });
});

describe('VirtualCutPlayer clips', () => {
  it('offers no clip buttons for a single span', () => {
    readyState = 1;
    renderPlayer(ready([cut(10, 20)]));

    expect(screen.queryByRole('button', { name: /Clip/ })).toBeNull();
    expect(screen.getByText(/1 span of this meeting/)).toBeInTheDocument();
  });

  it('seeks to the chosen span', () => {
    readyState = 1;
    renderPlayer(ready([cut(10, 20), cut(100, 130)]));

    expect(currentTime).toBe(10);

    fireEvent.click(screen.getByRole('button', { name: /Clip 2/ }));

    expect(currentTime).toBe(100);
  });

  it('counts the spans and the recording length', () => {
    readyState = 1;
    renderPlayer(ready([cut(10, 20), cut(100, 130)]));

    expect(
      screen.getByText(/2 spans of this meeting discussed this version/)
    ).toBeInTheDocument();
    expect(screen.getByText(/recording is 250s long/)).toBeInTheDocument();
  });

  // The clip indices belong to the version on screen. Keeping "Clip 3" selected across a change
  // would play a span of an unrelated version.
  it('returns to the first span when the version changes', () => {
    readyState = 1;
    const data = {
      ...ready([cut(10, 20), cut(100, 130)]),
      versions: [
        {
          version_id: VERSION_ID,
          body_hash: 'a',
          cuts: [cut(10, 20), cut(100, 130)],
        },
        { version_id: 999, body_hash: 'b', cuts: [cut(200, 210)] },
      ],
    };
    const { rerender } = renderPlayer(data);

    fireEvent.click(screen.getByRole('button', { name: /Clip 2/ }));
    expect(currentTime).toBe(100);

    rerender(
      <VirtualCutPlayer
        data={data}
        isLoading={false}
        error={null}
        versionId={999}
      />
    );

    expect(currentTime).toBe(200);
  });
});

/**
 * A blank box is indistinguishable from a bug, and these situations want different things from
 * the viewer — wait, come back later, stop waiting, or go tick a box. Each is asserted on the
 * distinguishing part of its wording, not the whole sentence.
 */
describe('VirtualCutPlayer empty states', () => {
  it.each<[RecordingCutsStatus, RegExp]>([
    ['no_meeting', /No meeting has run on this playlist yet/],
    ['no_recording', /This meeting was not recorded/],
    ['pending', /being recorded now/],
    ['archiving', /being collected and verified/],
    ['no_segments', /nothing was transcribed against these versions/],
    ['blocked', /cannot be saved to the share/],
  ])('says what %s means, and renders no player', (status, message) => {
    renderPlayer(empty(status));

    expect(screen.getByText(message)).toBeInTheDocument();
    expect(document.querySelector('video')).toBeNull();
  });

  it('marks a blocked recording as an alert, not another line of grey', () => {
    // The complaint that prompted this: set in the same muted text as "come back in a minute",
    // a message that needs someone to go and do something reads as more of the same and is
    // scrolled past. Asserted on the role rather than the colour, which is the part that has to
    // stay true if the palette moves.
    renderPlayer(empty('blocked', 'nite/lib.recording/pix/ref/dna does not exist.'));

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('This recording has not been saved');
    expect(alert).toHaveTextContent(/nite\/lib\.recording/);
  });

  it('does not shout about an ordinary wait', () => {
    renderPlayer(empty('archiving'));

    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('passes on the reason a blocked collection gives, since only it names the fix', () => {
    renderPlayer(
      empty(
        'blocked',
        'nite/lib.recording/pix/ref/dna does not exist on the recordings share.'
      )
    );

    expect(
      screen.getByText(/nite\/lib\.recording\/pix\/ref\/dna does not exist/)
    ).toBeInTheDocument();
    expect(document.querySelector('video')).toBeNull();
  });

  it('distinguishes a version nobody discussed from a meeting nobody recorded', () => {
    renderPlayer(ready([cut(10, 20)]), 999);

    expect(
      screen.getByText(
        /This version was not discussed in the meeting recording/
      )
    ).toBeInTheDocument();
    expect(document.querySelector('video')).toBeNull();
  });

  it('reports a failure to load rather than silently showing nothing', () => {
    render(
      <VirtualCutPlayer
        data={undefined}
        isLoading={false}
        error={new Error('upstream is down')}
        versionId={VERSION_ID}
      />
    );

    expect(screen.getByText(/upstream is down/)).toBeInTheDocument();
  });

  it('says it is loading while the answer is on its way', () => {
    render(
      <VirtualCutPlayer
        data={undefined}
        isLoading
        error={null}
        versionId={VERSION_ID}
      />
    );

    expect(screen.getByText('Loading…')).toBeInTheDocument();
  });
});
