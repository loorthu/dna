import { describe, expect, it } from 'vitest';
import {
  interpretMediaProbe,
  recordingReadiness,
  type ReadinessCheckId,
  type ReadinessInputs,
  type ReadinessState,
} from './useRecordingReadiness';

/** A settled, everything-landed baseline, so each test states only what it is about. */
function inputs(overrides: Partial<ReadinessInputs> = {}): ReadinessInputs {
  return {
    hasMeeting: true,
    botStatus: 'completed',
    recordingCapable: true,
    cuts: 'ready',
    cutsDetail: null,
    cutsLoading: false,
    cutsError: false,
    probe: { state: 'served' },
    ...overrides,
  };
}

describe('a recording the collector cannot file', () => {
  it('holds the gate instead of passing as archived', () => {
    // It passed before: everything that was not `pending` or `archiving` was taken for archived,
    // so the gate opened on a recording that is not on the share and the email linked to it.
    const result = recordingReadiness(
      inputs({
        cuts: 'blocked',
        cutsDetail: 'nite/lib.recording/pix/ref/dna does not exist.',
        probe: { state: 'not_yet' },
      })
    );

    expect(stateOf(result, 'archived')).toBe('blocked');
    expect(result.blocking).toBe(true);
  });

  it('says what is wrong, since waiting alone gives nobody the fix', () => {
    const result = recordingReadiness(
      inputs({
        cuts: 'blocked',
        cutsDetail: 'nite/lib.recording/pix/ref/dna does not exist.',
        probe: { state: 'not_yet' },
      })
    );

    expect(result.checks.find((c) => c.id === 'archived')?.detail).toMatch(
      /nite\/lib\.recording/
    );
  });

  it('is not the same state as an ordinary wait', () => {
    // They hold the gate alike and mean opposite things to whoever is looking: one resolves on
    // its own in about a minute, the other never does. The panel draws them differently, which
    // it can only do if they are different here.
    const stuck = recordingReadiness(
      inputs({
        cuts: 'blocked',
        cutsDetail: 'no directory',
        probe: { state: 'not_yet' },
      })
    );
    const waiting = recordingReadiness(
      inputs({ cuts: 'archiving', probe: { state: 'not_yet' } })
    );

    expect(stateOf(stuck, 'archived')).not.toBe(stateOf(waiting, 'archived'));
    expect(stuck.blocking).toBe(waiting.blocking);
  });

  it('is not counted among the passed checks', () => {
    const result = recordingReadiness(
      inputs({
        cuts: 'blocked',
        cutsDetail: 'no directory',
        probe: { state: 'not_yet' },
      })
    );

    expect(result.passed).toBeLessThan(result.total);
  });

  it('still counts the bot as gone — the upload finished before it blocked', () => {
    // Otherwise one problem holds two rows and neither of them names it.
    const result = recordingReadiness(
      inputs({
        cuts: 'blocked',
        cutsDetail: 'no directory',
        botStatus: undefined,
        probe: { state: 'not_yet' },
      })
    );

    expect(stateOf(result, 'bot_left')).toBe('pass');
  });
});

function stateOf(
  result: ReturnType<typeof recordingReadiness>,
  id: ReadinessCheckId
): ReadinessState | undefined {
  return result.checks.find((c) => c.id === id)?.state;
}

describe('recordingReadiness', () => {
  it('says nothing at all about a playlist no bot has run on', () => {
    // The state every playlist is in before a dispatch, and the one the dialog opens in most of
    // the time. A panel of grey ticks about a meeting that never happened is worse than no panel.
    const result = recordingReadiness(
      inputs({
        hasMeeting: false,
        cuts: 'no_meeting',
        botStatus: undefined,
        probe: { state: 'not_yet' },
      })
    );
    expect(result.applicable).toBe(false);
    expect(result.blocking).toBe(false);
    expect(result.checks).toEqual([]);
  });

  it('shows the panel on a dispatch the cut list has seen before the metadata has', () => {
    // The two sources disagree for one moment after a dispatch. Answering "no meeting" there
    // would hide the panel at exactly the moment it starts being worth showing.
    const result = recordingReadiness(
      inputs({
        hasMeeting: false,
        cuts: 'pending',
        botStatus: 'in_call',
        probe: { state: 'not_yet' },
      })
    );
    expect(result.applicable).toBe(true);
  });

  it('holds while the bot is still in the call', () => {
    const result = recordingReadiness(
      inputs({
        botStatus: 'transcribing',
        cuts: 'pending',
        probe: { state: 'not_yet' },
      })
    );
    expect(stateOf(result, 'bot_left')).toBe('waiting');
    expect(stateOf(result, 'archived')).toBe('waiting');
    expect(result.blocking).toBe(true);
    expect(result.passed).toBe(0);
    expect(result.total).toBe(3);
  });

  it('holds while the collector is taking custody, though the bot has gone', () => {
    const result = recordingReadiness(
      inputs({
        botStatus: 'completed',
        cuts: 'archiving',
        probe: { state: 'not_yet' },
      })
    );
    expect(stateOf(result, 'bot_left')).toBe('pass');
    expect(stateOf(result, 'archived')).toBe('waiting');
    expect(stateOf(result, 'served')).toBe('waiting');
    expect(result.blocking).toBe(true);
    expect(result.passed).toBe(1);
  });

  it('clears once the archive is recorded and this browser can fetch it', () => {
    const result = recordingReadiness(inputs());
    expect(result.blocking).toBe(false);
    expect(result.passed).toBe(3);
    expect(result.total).toBe(3);
  });

  it('treats a recorded meeting with no segments as landed', () => {
    // `no_segments` means archived — it is a statement about the transcript, not the media, and
    // reading it as "not ready" would hold the gate shut on a meeting that is entirely finished.
    const result = recordingReadiness(inputs({ cuts: 'no_segments' }));
    expect(stateOf(result, 'archived')).toBe('pass');
    expect(result.blocking).toBe(false);
  });

  it('lets a completed upload overrule a bot session that never reported leaving', () => {
    // A missed `bot.status_changed` frame leaves a live-looking session in the cache forever.
    // The recording index is server truth and can only reach `archiving` after the bot is gone,
    // so it wins — otherwise a stale frame holds the gate shut for the rest of the day.
    const result = recordingReadiness(
      inputs({
        botStatus: 'in_call',
        cuts: 'archiving',
        probe: { state: 'not_yet' },
      })
    );
    expect(stateOf(result, 'bot_left')).toBe('pass');
  });

  it('skips the archive check when the meeting was not recorded', () => {
    const result = recordingReadiness(
      inputs({ cuts: 'no_recording', botStatus: 'completed' })
    );
    expect(stateOf(result, 'archived')).toBe('skipped');
    expect(stateOf(result, 'served')).toBe('skipped');
    expect(result.blocking).toBe(false);
    // Skipped checks are not counted, so the tally cannot read "1 of 3" on a meeting where the
    // other two were never going to happen.
    expect(result.total).toBe(1);
    expect(result.passed).toBe(1);
  });

  it('skips the archive check in a deployment that does not record', () => {
    const result = recordingReadiness(
      inputs({
        recordingCapable: false,
        cuts: undefined,
        probe: { state: 'not_yet' },
      })
    );
    expect(stateOf(result, 'archived')).toBe('skipped');
    expect(stateOf(result, 'served')).toBe('skipped');
    expect(result.blocking).toBe(false);
  });

  it('holds briefly while the archive answer is still being fetched', () => {
    const result = recordingReadiness(
      inputs({ cuts: undefined, cutsLoading: true })
    );
    expect(stateOf(result, 'archived')).toBe('checking');
    expect(result.blocking).toBe(true);
  });

  it('never blocks on a check it could not run', () => {
    // A status endpoint being down is not evidence that anything is wrong with the recording,
    // and refusing to send notes over it helps nobody. Reported, not enforced.
    const result = recordingReadiness(
      inputs({
        cuts: undefined,
        cutsError: true,
        botStatus: undefined,
        probe: { state: 'not_yet' },
      })
    );
    expect(stateOf(result, 'archived')).toBe('unknown');
    expect(stateOf(result, 'bot_left')).toBe('unknown');
    // The probe cannot be meaningful without a media URL to probe, and a check that could not
    // run must not be the thing that holds the gate.
    expect(stateOf(result, 'served')).toBe('unknown');
    expect(result.blocking).toBe(false);
  });

  it('holds when this browser cannot fetch the archive DNA says exists', () => {
    // The failure the API cannot see: the collector wrote and verified the file on the share, and
    // the origin serving this page does not hand it out. Every link in the email would 404.
    const result = recordingReadiness(
      inputs({
        probe: {
          state: 'missing',
          detail: 'Archived, but this server is not serving it (404).',
        },
      })
    );
    expect(stateOf(result, 'archived')).toBe('pass');
    expect(stateOf(result, 'served')).toBe('waiting');
    expect(result.blocking).toBe(true);
    // The reason survives into the panel — "not served" alone sends someone looking in the wrong
    // place, and the three causes have three different owners.
    expect(result.checks.find((c) => c.id === 'served')?.detail).toContain(
      '404'
    );
  });

  it('reports the probe as checking while it is in flight', () => {
    const result = recordingReadiness(inputs({ probe: { state: 'checking' } }));
    expect(stateOf(result, 'served')).toBe('checking');
    expect(result.blocking).toBe(true);
  });
});

describe('interpretMediaProbe', () => {
  it('passes a served file', () => {
    expect(
      interpretMediaProbe({ ok: true, status: 200, contentLength: '512000000' })
    ).toEqual({ ok: true, detail: '' });
  });

  it('accepts a served file whose length the server did not state', () => {
    // A chunked or length-less 200 is still a served file. Requiring the header would fail the
    // check on a working deployment, which is the one outcome this row must never produce.
    expect(
      interpretMediaProbe({ ok: true, status: 200, contentLength: null }).ok
    ).toBe(true);
  });

  it('points a 404 at the mount and a 403 at the code', () => {
    expect(
      interpretMediaProbe({ ok: false, status: 404, contentLength: null })
        .detail
    ).toContain('recordings mount');
    expect(
      interpretMediaProbe({ ok: false, status: 403, contentLength: null })
        .detail
    ).toContain('403');
  });

  it('fails a zero-length file that answered 200', () => {
    const result = interpretMediaProbe({
      ok: true,
      status: 200,
      contentLength: '0',
    });
    expect(result.ok).toBe(false);
    expect(result.detail).toContain('empty');
  });

  it('reads an unfinished fetch as unreachable, not as an error', () => {
    expect(interpretMediaProbe(null).ok).toBe(false);
  });
});
