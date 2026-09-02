import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '../test/render';
import userEvent from '@testing-library/user-event';
import { EmailNotesDialog } from './EmailNotesDialog';
import { useRecordingReadiness } from '../hooks/useRecordingReadiness';
import type { RecordingReadiness } from '../hooks/useRecordingReadiness';

const mockSend = vi.fn().mockResolvedValue({});
const mockReset = vi.fn();

vi.mock('../hooks/useEmailNotes', () => ({
  useEmailNotes: () => ({
    mutateAsync: mockSend,
    isPending: false,
    isError: false,
    error: null,
    reset: mockReset,
  }),
}));

vi.mock('../hooks/useRecordingReadiness', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../hooks/useRecordingReadiness')>();
  return { ...actual, useRecordingReadiness: vi.fn() };
});

const mockedReadiness = vi.mocked(useRecordingReadiness);

const NOTHING_PENDING: RecordingReadiness = {
  applicable: false,
  checks: [],
  blocking: false,
  passed: 0,
  total: 0,
};

const STILL_ARCHIVING: RecordingReadiness = {
  applicable: true,
  blocking: true,
  passed: 1,
  total: 3,
  checks: [
    {
      id: 'bot_left',
      state: 'pass',
      label: 'Bot has left the meeting',
      detail: 'Bot is completed.',
    },
    {
      id: 'archived',
      state: 'waiting',
      label: 'Recording archived and verified',
      detail: 'Upload finished — the collector is taking custody.',
    },
    {
      id: 'served',
      state: 'waiting',
      label: 'Playable from this network',
      detail: 'Waiting for the archive.',
    },
  ],
};

/** Archived and verified upstream, and this browser still cannot fetch it. */
const NOT_SERVED_HERE: RecordingReadiness = {
  applicable: true,
  blocking: true,
  passed: 2,
  total: 3,
  checks: [
    { ...STILL_ARCHIVING.checks[0] },
    {
      id: 'archived',
      state: 'pass',
      label: 'Recording archived and verified',
      detail: 'Written to the recording host, read back and hashed.',
    },
    {
      id: 'served',
      state: 'waiting',
      label: 'Playable from this network',
      detail:
        'Archived, but this server is not serving it (404) — check the recordings mount.',
    },
  ],
};

function renderDialog(props: { unpublishedCount?: number } = {}) {
  return render(
    <EmailNotesDialog
      open
      onClose={() => {}}
      playlistId={1}
      userEmail="me@test.com"
      {...props}
    />
  );
}

describe('EmailNotesDialog readiness gate', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('sends without ceremony when there is no meeting to wait for', async () => {
    // The ordinary case: notes on a playlist nobody dispatched a bot to. The gate must be
    // invisible there, not merely satisfied.
    mockedReadiness.mockReturnValue(NOTHING_PENDING);
    const user = userEvent.setup();
    renderDialog();

    expect(screen.queryByText('MEETING READINESS')).toBeNull();
    await user.type(
      screen.getByPlaceholderText('recipient@example.com'),
      'a@b.com'
    );
    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(mockSend).toHaveBeenCalledTimes(1);
  });

  it('names what is outstanding and holds Send while the recording lands', async () => {
    mockedReadiness.mockReturnValue(STILL_ARCHIVING);
    const user = userEvent.setup();
    renderDialog();

    expect(screen.getByText('Recording archived and verified')).toBeTruthy();
    await user.type(
      screen.getByPlaceholderText('recipient@example.com'),
      'a@b.com'
    );
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    expect(mockSend).not.toHaveBeenCalled();
  });

  it('sends on an explicit override, and says what is being overridden', async () => {
    mockedReadiness.mockReturnValue(STILL_ARCHIVING);
    const user = userEvent.setup();
    renderDialog();

    await user.type(
      screen.getByPlaceholderText('recipient@example.com'),
      'a@b.com'
    );
    await user.click(
      screen.getByRole('button', { name: 'Send anyway (1 of 3 ready)' })
    );
    // Two clicks by design: the override arms the button rather than sending, so the decision to
    // send early is made deliberately and not by a stray click on a button that just moved.
    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(mockSend).toHaveBeenCalledTimes(1);
  });

  it('names the serving fault rather than just refusing', async () => {
    // The row the API cannot fill in. Someone reading this needs to know the recording is safe
    // and the SHARE is the problem — "not ready" alone reads as a lost meeting.
    mockedReadiness.mockReturnValue(NOT_SERVED_HERE);
    renderDialog();

    expect(screen.getByText(/check the recordings mount/)).toBeTruthy();
    expect(
      screen.getByRole('button', { name: 'Send anyway (2 of 3 ready)' })
    ).toBeTruthy();
  });

  it('offers no override when nothing is being held', async () => {
    mockedReadiness.mockReturnValue({
      ...STILL_ARCHIVING,
      blocking: false,
      passed: 2,
      checks: STILL_ARCHIVING.checks.map((c) => ({
        ...c,
        state: 'pass' as const,
      })),
    });
    renderDialog();

    expect(screen.queryByText(/Send anyway/)).toBeNull();
  });
});

describe('EmailNotesDialog unpublished-notes warning', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Isolate this from the readiness gate, which blocks on its own terms.
    mockedReadiness.mockReturnValue(NOTHING_PENDING);
  });

  it('says nothing when everything has been published', () => {
    renderDialog({ unpublishedCount: 0 });
    expect(screen.queryByText(/not been published/i)).toBeNull();
  });

  it('warns but still sends when notes are unpublished', async () => {
    // The whole point: the expected order is publish then email, but a person who
    // knows what they are doing must not be stopped — only told.
    const user = userEvent.setup();
    renderDialog({ unpublishedCount: 3 });

    expect(
      screen.getByText(/3 notes have not been published to ShotGrid yet/i)
    ).toBeTruthy();

    const send = screen.getByRole('button', { name: 'Send' });
    await user.type(
      screen.getByPlaceholderText('recipient@example.com'),
      'a@b.com'
    );
    expect(send.hasAttribute('disabled')).toBe(false);

    await user.click(send);
    expect(mockSend).toHaveBeenCalledTimes(1);
  });

  it('counts one note in the singular', () => {
    renderDialog({ unpublishedCount: 1 });
    expect(
      screen.getByText(/1 note has not been published to ShotGrid yet/i)
    ).toBeTruthy();
  });
});
