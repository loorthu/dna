import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';
import { pollIntervalFor, useRecordingCuts } from './useRecordingCuts';
import { apiHandler } from '../api';
import type { PlaylistRecordingCuts, RecordingCutsStatus } from '@dna/core';

vi.mock('../api', () => ({
  apiHandler: { getRecordingCuts: vi.fn() },
}));

const mockedApiHandler = vi.mocked(apiHandler);

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

function cuts(status: RecordingCutsStatus): PlaylistRecordingCuts {
  return {
    playlist_id: 42,
    status,
    media_url: status === 'ready' ? '/recordings/playlist-42-rec7.mp4' : null,
    duration_seconds: status === 'ready' ? 156.4 : null,
    recording_t0: status === 'ready' ? '2026-08-21T21:27:39.777Z' : null,
    recording_t0_source: status === 'ready' ? 'vexa_recorder_clock' : null,
    versions:
      status === 'ready'
        ? [
            {
              version_id: 5701144,
              body_hash: '9ff2833b806b',
              cuts: [
                {
                  video_in_seconds: 61.155,
                  video_out_seconds: 62.179,
                  transcript_segment_ids: ['a'],
                },
              ],
            },
          ]
        : [],
  };
}

describe('useRecordingCuts', () => {
  beforeEach(() => vi.clearAllMocks());

  it('does not ask until a playlist is selected', () => {
    renderHook(() => useRecordingCuts(null), { wrapper: createWrapper() });

    expect(mockedApiHandler.getRecordingCuts).not.toHaveBeenCalled();
  });

  it('returns the cut list for a playlist', async () => {
    mockedApiHandler.getRecordingCuts.mockResolvedValue(cuts('ready'));

    const { result } = renderHook(() => useRecordingCuts(42), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.status).toBe('ready');
    expect(result.current.data?.versions[0].cuts[0].video_in_seconds).toBe(
      61.155
    );
    expect(mockedApiHandler.getRecordingCuts).toHaveBeenCalledWith({
      playlistId: 42,
    });
  });
});

// The polling rule as a rule. Through the hook it could only be checked by inspecting TanStack's
// internals, which produced assertions that held whatever the code did — worse than no test,
// because it looked covered.
describe('pollIntervalFor', () => {
  it.each<RecordingCutsStatus>(['pending', 'archiving'])(
    'keeps asking while %s — the answer is still moving',
    (status) => {
      expect(pollIntervalFor(status)).toBe(10_000);
    }
  );

  it.each<RecordingCutsStatus>(['ready', 'no_recording', 'no_segments'])(
    'stops asking once %s — nothing can change it from here',
    (status) => {
      expect(pollIntervalFor(status)).toBe(false);
    }
  );

  it('does not poll before the first answer arrives', () => {
    expect(pollIntervalFor(undefined)).toBe(false);
  });
});
