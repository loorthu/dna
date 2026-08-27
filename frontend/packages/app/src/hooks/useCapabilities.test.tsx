import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';
import { useCapabilities } from './useCapabilities';
import { apiHandler } from '../api';

vi.mock('../api', () => ({
  apiHandler: { getCapabilities: vi.fn() },
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

describe('useCapabilities', () => {
  beforeEach(() => vi.clearAllMocks());

  it('reports what the deployment says it supports', async () => {
    mockedApiHandler.getCapabilities.mockResolvedValue({
      recording_playback: true,
    });

    const { result } = renderHook(() => useCapabilities(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.recording_playback).toBe(true));
  });

  // Before the answer arrives, and after one that never does. Both have to hide the feature: a
  // tab shown on an assumption is a tab whose every request 404s.
  it('claims nothing before the answer arrives', () => {
    mockedApiHandler.getCapabilities.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useCapabilities(), {
      wrapper: createWrapper(),
    });

    expect(result.current.recording_playback).toBe(false);
  });

  it('claims nothing when the deployment cannot be asked', async () => {
    // An older back end has no /capabilities at all, and it has no recording pipeline either —
    // the failure and the honest answer happen to agree.
    mockedApiHandler.getCapabilities.mockRejectedValue(new Error('404'));

    const { result } = renderHook(() => useCapabilities(), {
      wrapper: createWrapper(),
    });

    await waitFor(() =>
      expect(mockedApiHandler.getCapabilities).toHaveBeenCalled()
    );
    expect(result.current.recording_playback).toBe(false);
  });

  it('asks once, not per component', async () => {
    mockedApiHandler.getCapabilities.mockResolvedValue({
      recording_playback: true,
    });
    const wrapper = createWrapper();

    const { result } = renderHook(
      () => [useCapabilities(), useCapabilities()],
      { wrapper }
    );

    await waitFor(() =>
      expect(result.current[1].recording_playback).toBe(true)
    );
    expect(mockedApiHandler.getCapabilities).toHaveBeenCalledTimes(1);
  });
});
