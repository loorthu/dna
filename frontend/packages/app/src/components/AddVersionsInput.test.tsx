import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '../test/render';
import userEvent from '@testing-library/user-event';
import { AddVersionsInput } from './AddVersionsInput';
import { parseJtsNumbers, summariseAddOutcomes } from '../hooks/useAddVersion';

const mockAdd = vi.fn();
const showToast = vi.fn();
let isPending = false;

vi.mock('../hooks', async () => {
  const actual = await import('../hooks/useAddVersion');
  return {
    parseJtsNumbers: actual.parseJtsNumbers,
    summariseAddOutcomes: actual.summariseAddOutcomes,
    useAddVersionsToPlaylist: () => ({ mutateAsync: mockAdd, isPending }),
  };
});

vi.mock('../contexts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../contexts')>();
  return { ...actual, useToast: () => ({ showToast, dismissToast: vi.fn() }) };
});

function added(jts: number, name: string) {
  return {
    jts,
    status: 'added' as const,
    version_id: 900 + jts,
    version_name: name,
  };
}

async function openAndType(text: string) {
  const user = userEvent.setup();
  render(<AddVersionsInput playlistId={400} />);
  await user.click(screen.getByRole('button', { name: 'Add Version' }));
  await user.type(screen.getByLabelText('JTS numbers'), text);
  return user;
}

describe('parseJtsNumbers', () => {
  it('takes a list however it was pasted', () => {
    // A column out of a spreadsheet, a comma-separated line, and version names with the
    // bracketed prefix are all the same list to whoever pasted them.
    expect(parseJtsNumbers('1786, 1787, 1789')).toEqual([1786, 1787, 1789]);
    expect(parseJtsNumbers('1786\n1787\n1789')).toEqual([1786, 1787, 1789]);
    expect(parseJtsNumbers('[1786] a  [1787] b')).toEqual([1786, 1787]);
  });

  it('keeps the pasted order and drops repeats', () => {
    expect(parseJtsNumbers('1789, 1786, 1789')).toEqual([1789, 1786]);
  });

  it('finds nothing in text with no numbers', () => {
    expect(parseJtsNumbers('nite-seq.pvs')).toEqual([]);
    expect(parseJtsNumbers('')).toEqual([]);
  });
});

describe('summariseAddOutcomes', () => {
  it('names what landed', () => {
    const summary = summariseAddOutcomes([added(1790, '[1790] camera-123')]);

    expect(summary.type).toBe('success');
    expect(summary.title).toBe('Version added');
    expect(summary.description).toContain('[1790] camera-123');
  });

  it('counts them when there are several', () => {
    const summary = summariseAddOutcomes([
      added(1790, '[1790] camera-123'),
      added(1791, '[1791] camera-124'),
    ]);

    expect(summary.title).toBe('2 versions added');
  });

  it('warns, and names the numbers, when some of a paste did not land', () => {
    // The counts alone would hide which ones; these are the numbers somebody has to go check.
    const summary = summariseAddOutcomes([
      added(1790, '[1790] camera-123'),
      {
        jts: 1789,
        status: 'already_in_playlist',
        version_id: 1,
        version_name: 'x',
      },
      { jts: 999999, status: 'not_found' },
    ]);

    expect(summary.type).toBe('warning');
    expect(summary.title).toBe('Version added');
    expect(summary.description).toContain('1789 already in the playlist');
    expect(summary.description).toContain('999999 not on this show');
  });

  it('is not an error when everything asked for was already there', () => {
    const summary = summariseAddOutcomes([
      {
        jts: 1789,
        status: 'already_in_playlist',
        version_id: 1,
        version_name: 'x',
      },
    ]);

    expect(summary.type).toBe('info');
    expect(summary.title).toBe('Already in this playlist');
  });

  it('is an error when nothing was found at all', () => {
    const summary = summariseAddOutcomes([
      { jts: 999999, status: 'not_found' },
    ]);

    expect(summary.type).toBe('error');
    expect(summary.title).toBe('Nothing added');
  });

  it('does not list a whole pasted column back at someone', () => {
    const summary = summariseAddOutcomes(
      [1, 2, 3, 4, 5].map((n) => added(n, `v${n}`))
    );

    expect(summary.description).toContain('and 2 more');
  });
});

describe('AddVersionsInput', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    isPending = false;
    mockAdd.mockResolvedValue({
      outcomes: [added(1787, '[1787] camera-121')],
      added_count: 1,
    });
  });

  it('stays out of the way until it is asked for', () => {
    // One + on the title line beside the search, and nothing of the field until it is wanted.
    render(<AddVersionsInput playlistId={400} />);

    expect(screen.getByRole('button', { name: 'Add Version' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Close' })).toBeNull();
  });

  it('tells the row when it takes it over, so the search stands down', async () => {
    const onExpandedChange = vi.fn();
    const user = userEvent.setup();
    render(
      <AddVersionsInput playlistId={400} onExpandedChange={onExpandedChange} />
    );

    await user.click(screen.getByRole('button', { name: 'Add Version' }));

    expect(onExpandedChange).toHaveBeenLastCalledWith(true);
  });

  it('sends the whole pasted list on Enter', async () => {
    const user = await openAndType('1786, 1787, 1789');
    await user.keyboard('{Enter}');

    expect(mockAdd).toHaveBeenCalledWith({
      playlistId: 400,
      jts: [1786, 1787, 1789],
    });
  });

  it('counts what it read, so a mis-paste is visible before it is sent', async () => {
    await openAndType('1786 1787 1789');

    expect(screen.getByText('3')).toBeTruthy();
  });

  it('reports through a toast rather than holding the sidebar', async () => {
    const user = await openAndType('1787');
    await user.keyboard('{Enter}');

    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'success', title: 'Version added' })
    );
  });

  it('closes itself once everything landed', async () => {
    const user = await openAndType('1787');
    await user.keyboard('{Enter}');

    expect(screen.getByRole('button', { name: 'Add Version' })).toBeTruthy();
  });

  it('keeps the numbers that found nothing, and stays open on them', async () => {
    mockAdd.mockResolvedValue({
      outcomes: [
        added(1787, '[1787] camera-121'),
        { jts: 4242, status: 'not_found' },
      ],
      added_count: 1,
    });
    const user = await openAndType('1787 4242');
    await user.keyboard('{Enter}');

    const field = screen.getByLabelText('JTS numbers') as HTMLInputElement;
    expect(field.value).toBe('4242');
  });

  it('says what the backend refused, not the status code', async () => {
    mockAdd.mockRejectedValue({
      message: 'Request failed with status code 501',
      response: {
        data: { detail: 'Set PRODTRACK_VERSION_EXTERNAL_REF_FIELD.' },
      },
    });
    const user = await openAndType('1787');
    await user.keyboard('{Enter}');

    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'error',
        description: 'Set PRODTRACK_VERSION_EXTERNAL_REF_FIELD.',
      })
    );
  });

  it('will not send a box with no numbers in it', async () => {
    const user = await openAndType('nite-seq');
    await user.keyboard('{Enter}');

    expect(mockAdd).not.toHaveBeenCalled();
  });

  it('offers nothing to click when no playlist is open', () => {
    render(<AddVersionsInput playlistId={null} />);

    expect(screen.getByRole('button', { name: 'Add Version' })).toBeDisabled();
  });
});
