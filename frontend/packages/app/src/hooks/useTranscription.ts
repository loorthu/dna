import { useState, useCallback, useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type {
  BotSession,
  BotStatus,
  BotStatusEnum,
  DispatchBotRequest,
  Platform,
  BotStatusEventPayload,
  DNAEvent,
} from '@dna/core';
import { apiHandler } from '../api';
import { usePlaylistMetadata } from './usePlaylistMetadata';
import { useEventClient, useToast } from '../contexts';

export interface ParsedMeetingUrl {
  platform: Platform;
  meetingId: string;
}

export function parseMeetingUrl(url: string): ParsedMeetingUrl | null {
  const trimmedUrl = url.trim();

  const googleMeetMatch = trimmedUrl.match(
    /meet\.google\.com\/([a-z]{3}-[a-z]{4}-[a-z]{3})/i
  );
  if (googleMeetMatch) {
    return {
      platform: 'google_meet',
      meetingId: googleMeetMatch[1].toLowerCase(),
    };
  }

  const teamsMatch = trimmedUrl.match(/teams\.microsoft\.com.*meetup-join/i);
  if (teamsMatch) {
    return {
      platform: 'teams',
      meetingId: trimmedUrl,
    };
  }

  if (/^[a-z]{3}-[a-z]{4}-[a-z]{3}$/i.test(trimmedUrl)) {
    return {
      platform: 'google_meet',
      meetingId: trimmedUrl.toLowerCase(),
    };
  }

  return null;
}

const ACTIVE_STATUSES: BotStatusEnum[] = [
  'joining',
  'waiting_room',
  'in_call',
  'transcribing',
];

function isActiveStatus(statusValue: BotStatusEnum | undefined): boolean {
  return statusValue !== undefined && ACTIVE_STATUSES.includes(statusValue);
}

/**
 * Where a playlist's bot session lives.
 *
 * It is React state in all but name — nothing fetches it, and its only writers are this file's
 * mutations and its `bot.status_changed` subscription. It sits in the query cache rather than in
 * `useState` so that components far from this hook can read it: the Set In Review button in the
 * version header has to know a bot is live before it can warn that the transcript is going
 * nowhere, and it is nowhere near the transcription menu in the tree.
 */
export function botSessionQueryKey(playlistId: number | null) {
  return ['botSession', playlistId] as const;
}

export function isBotSessionLive(session: BotSession | null): boolean {
  return isActiveStatus(session?.status);
}

/** Read-only view of the session above, for anything that must not dispatch or stop a bot. */
export function useBotSession(playlistId: number | null): BotSession | null {
  const { data } = useQuery<BotSession | null>({
    queryKey: botSessionQueryKey(playlistId),
    // Never runs: the cache is a store, not a mirror of anything on the server.
    queryFn: () => null,
    enabled: false,
    initialData: null,
    staleTime: Infinity,
    gcTime: Infinity,
  });
  return data ?? null;
}

/**
 * The session a `bot.status_changed` frame leaves behind, or `null` to keep the one we have.
 *
 * Exported so the rule can be tested as a rule — the alternative is asserting it through a hook
 * that needs an event client, a query client and two contexts to exist first.
 *
 * The load-bearing part is that a frame may carry NO status. The backend reuses this event to
 * report what it noticed about a bot that is already running — segments being discarded, for one —
 * from a place that does not know the bot's current status. Writing that absent status through set
 * `session.status` to undefined, which reads as "not active", and the Stop button vanished from a
 * live meeting the moment the discard warning fired.
 */
export function nextSessionForStatusEvent(
  session: BotSession | null,
  payload: BotStatusEventPayload,
  playlistId: number
): BotSession | null {
  const newStatus = payload.status as BotStatusEnum | undefined;

  const advisory: Partial<BotSession> = {};
  if (payload.saving_segments !== undefined) {
    advisory.saving_segments = payload.saving_segments;
  }
  if (payload.warnings !== undefined) {
    advisory.warnings = payload.warnings;
  }

  if (session) {
    return {
      ...session,
      ...advisory,
      ...(newStatus ? { status: newStatus } : {}),
      updated_at: new Date().toISOString(),
    };
  }

  // No session yet: only a frame that says the bot is live can start one. An advisory frame
  // cannot — it has no status to judge, and inventing one would put a Stop button in front of a
  // bot that may already be gone.
  if (isActiveStatus(newStatus)) {
    return {
      platform: payload.platform as Platform,
      meeting_id: payload.meeting_id,
      playlist_id: payload.playlist_id ?? playlistId,
      status: newStatus as BotStatusEnum,
      ...advisory,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
  }

  return null;
}

export interface UseTranscriptionOptions {
  playlistId: number | null;
}

export interface UseTranscriptionReturn {
  session: BotSession | null;
  status: BotStatus | null;
  isDispatching: boolean;
  isStopping: boolean;
  isLoadingStatus: boolean;
  error: Error | null;
  dispatchBot: (
    meetingUrl: string,
    passcode?: string,
    recordingEnabled?: boolean
  ) => Promise<BotSession>;
  stopBot: () => Promise<void>;
  clearSession: () => void;
}

export function useTranscription({
  playlistId,
}: UseTranscriptionOptions): UseTranscriptionReturn {
  const queryClient = useQueryClient();
  const eventClient = useEventClient();
  const { showToast, dismissToast } = useToast();
  const session = useBotSession(playlistId);
  const setSession = useCallback(
    (next: BotSession | null) => {
      queryClient.setQueryData(botSessionQueryKey(playlistId), next);
    },
    [queryClient, playlistId]
  );
  const [error, setError] = useState<Error | null>(null);
  const previousStatusRef = useRef<BotStatusEnum | null>(null);
  const waitingRoomToastIdRef = useRef<string | null>(null);

  const { data: metadata, isLoading: isLoadingMetadata } =
    usePlaylistMetadata(playlistId);

  const meetingPlatform =
    session?.platform ?? (metadata?.platform as Platform | null);
  const meetingId = session?.meeting_id ?? metadata?.meeting_id;

  const shouldFetchInitialStatus = !!(
    meetingPlatform &&
    meetingId &&
    !session
  );

  const {
    data: status,
    isLoading: isLoadingStatus,
  } = useQuery<BotStatus, Error>({
    queryKey: ['botStatus', meetingPlatform, meetingId],
    queryFn: () =>
      apiHandler.getBotStatus({
        platform: meetingPlatform!,
        meetingId: meetingId!,
      }),
    enabled: shouldFetchInitialStatus,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    refetchOnReconnect: false,
  });

  if (import.meta.env.DEV) {
    console.log('[useTranscription]', {
      playlistId,
      metadata,
      isLoadingMetadata,
      meetingPlatform,
      meetingId,
      session,
      status,
      shouldFetchInitialStatus,
    });
  }

  useEffect(() => {
    const currentStatus = session?.status ?? status?.status;
    const previousStatus = previousStatusRef.current;

    if (currentStatus === 'waiting_room' && previousStatus !== 'waiting_room') {
      const toastId = showToast({
        title: 'Agent Waiting for Admission',
        description:
          'The transcription agent is waiting to be admitted to the call. Please admit the agent on the call platform.',
        type: 'warning',
        duration: 30000,
      });
      waitingRoomToastIdRef.current = toastId;
    }

    if (
      previousStatus === 'waiting_room' &&
      (currentStatus === 'in_call' || currentStatus === 'transcribing') &&
      waitingRoomToastIdRef.current
    ) {
      dismissToast(waitingRoomToastIdRef.current);
      waitingRoomToastIdRef.current = null;
    }

    previousStatusRef.current = currentStatus ?? null;
  }, [session?.status, status?.status, showToast, dismissToast]);

  useEffect(() => {
    if (status && !session && meetingPlatform && meetingId) {
      if (isActiveStatus(status.status)) {
        setSession({
          platform: meetingPlatform,
          meeting_id: meetingId,
          playlist_id: playlistId!,
          status: status.status,
          created_at: new Date().toISOString(),
          updated_at: status.updated_at,
        });
      }
    }
  }, [status, session, meetingPlatform, meetingId, playlistId, setSession]);

  useEffect(() => {
    if (!eventClient || !playlistId) return;

    const handleBotStatusEvent = (event: DNAEvent<BotStatusEventPayload>) => {
      const payload = event.payload;

      const matchesMeeting =
        meetingPlatform &&
        meetingId &&
        payload.platform === meetingPlatform &&
        payload.meeting_id === meetingId;

      const matchesPlaylist = payload.playlist_id === playlistId;

      if (!matchesMeeting && !matchesPlaylist) {
        return;
      }

      const newStatus = payload.status as BotStatusEnum | undefined;

      const next = nextSessionForStatusEvent(session, payload, playlistId);
      if (next) setSession(next);

      // An advisory frame says nothing about the status, so it must not write one into the status
      // cache either — that cache is what the UI falls back on when there is no session.
      if (!newStatus) return;

      queryClient.setQueryData<BotStatus>(
        ['botStatus', payload.platform, payload.meeting_id],
        (old) =>
          old
            ? { ...old, status: newStatus, updated_at: new Date().toISOString() }
            : {
                status: newStatus,
                updated_at: new Date().toISOString(),
              }
      );
    };

    const unsubscribe = eventClient.subscribe<BotStatusEventPayload>(
      'bot.status_changed',
      handleBotStatusEvent
    );

    return unsubscribe;
  }, [
    eventClient,
    meetingPlatform,
    meetingId,
    playlistId,
    session,
    queryClient,
    setSession,
  ]);

  const dispatchMutation = useMutation<BotSession, Error, DispatchBotRequest>({
    mutationFn: (request) => apiHandler.dispatchBot({ request }),
    onMutate: (request) => {
      setSession({
        platform: request.platform,
        meeting_id: request.meeting_id,
        playlist_id: request.playlist_id,
        status: 'joining',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
      setError(null);
    },
    onSuccess: (newSession) => {
      setSession(newSession);
      setError(null);
      queryClient.invalidateQueries({
        queryKey: ['playlistMetadata', playlistId],
      });
    },
    onError: (err) => {
      setSession(null);
      setError(err);
    },
  });

  const stopMutation = useMutation<boolean, Error, void>({
    mutationFn: async () => {
      if (!meetingPlatform || !meetingId) throw new Error('No active session');
      return apiHandler.stopBot({
        platform: meetingPlatform,
        meetingId: meetingId,
      });
    },
    onSuccess: () => {
      if (session) {
        setSession({ ...session, status: 'stopped' });
      }
    },
    onError: (err) => {
      setError(err);
    },
  });

  const dispatchBot = useCallback(
    async (
      meetingUrl: string,
      passcode?: string,
      recordingEnabled = false
    ): Promise<BotSession> => {
      if (!playlistId) {
        throw new Error('No playlist selected');
      }

      const parsed = parseMeetingUrl(meetingUrl);
      if (!parsed) {
        throw new Error('Invalid meeting URL format');
      }

      const request: DispatchBotRequest = {
        platform: parsed.platform,
        meeting_id: parsed.meetingId,
        playlist_id: playlistId,
        passcode,
        // Always stated, never left out: omitting it lets a default on the Vexa host decide
        // whether this meeting is recorded, which is a setting nobody here can see.
        recording_enabled: recordingEnabled,
      };

      return dispatchMutation.mutateAsync(request);
    },
    [playlistId, dispatchMutation]
  );

  const stopBot = useCallback(async (): Promise<void> => {
    await stopMutation.mutateAsync();
  }, [stopMutation]);

  const clearSession = useCallback(() => {
    setSession(null);
    setError(null);
  }, [setSession]);

  return {
    session,
    status: status ?? null,
    isDispatching: dispatchMutation.isPending,
    isStopping: stopMutation.isPending,
    isLoadingStatus,
    error,
    dispatchBot,
    stopBot,
    clearSession,
  };
}
