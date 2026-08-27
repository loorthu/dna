import { useQuery } from '@tanstack/react-query';
import type { DeploymentCapabilities } from '@dna/core';
import { apiHandler } from '../api';

/**
 * What this deployment can do, asked once.
 *
 * Playing a meeting back needs a recorder, a collector and a share, and the back end is the side
 * that knows whether they exist. This used to be mirrored into a front-end build flag AND a user
 * preference in the settings window — three settings for one fact, which is how a meeting came to
 * be recorded, archived and then hidden behind a switch nobody had been told about.
 *
 * Deployment-shaped, so it is asked once and kept: it cannot change without a restart of the
 * service that answers it.
 */
const CAPABILITIES_UNAVAILABLE: DeploymentCapabilities = {
  recording_playback: false,
};

export function useCapabilities(): DeploymentCapabilities {
  const { data } = useQuery<DeploymentCapabilities, Error>({
    queryKey: ['capabilities'],
    queryFn: () => apiHandler.getCapabilities(),
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    refetchOnReconnect: false,
    retry: 1,
  });

  // Absent means "not yet" and "could not ask" alike, and both should hide the feature rather
  // than offer one whose every request fails. An older back end without this endpoint 404s, which
  // lands here too — it has no recording pipeline either.
  return data ?? CAPABILITIES_UNAVAILABLE;
}
