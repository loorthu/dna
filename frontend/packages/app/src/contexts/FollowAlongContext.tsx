import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import {
  ReviewSyncClient,
  createReviewSyncClient,
  fetchReviewSessions,
  sortReviewSessions,
  type ReviewFocus,
  type ReviewSession,
} from '@dna/core';
import { readFollowAlongConfig } from '../followAlong/config';
import { useFeatureFlags } from './FeatureFlagsContext';

const CONFIG = readFollowAlongConfig();

function sessionStorageKey(playlistId: number): string {
  return `dna-follow-along-session:${playlistId}`;
}

interface FollowAlongContextValue {
  /** Configured by the site and enabled by the user. */
  available: boolean;
  /** The site configured a session directory we can list sessions from. */
  hasSessionDirectory: boolean;
  connected: boolean;
  connectionError: Error | null;
  sessions: ReviewSession[];
  sessionsLoading: boolean;
  sessionsError: Error | null;
  refreshSessions: () => void;
  session: string | null;
  setSession: (session: string | null) => void;
  focus: ReviewFocus | null;
  show: string | null;
  setShow: (show: string | null) => void;
  playlistId: number | null;
  setPlaylistId: (playlistId: number | null) => void;
}

const FollowAlongContext = createContext<FollowAlongContextValue | null>(null);

interface FollowAlongProviderProps {
  children: ReactNode;
  /** Stands in for the configured broker connection. For tests. */
  client?: ReviewSyncClient;
}

export function FollowAlongProvider({
  children,
  client: injectedClient,
}: FollowAlongProviderProps) {
  const { followAlongEnabled } = useFeatureFlags();
  const available = (CONFIG !== null || !!injectedClient) && followAlongEnabled;

  const clientRef = useRef<ReviewSyncClient | null>(null);
  const [connected, setConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<Error | null>(null);
  const [focus, setFocus] = useState<ReviewFocus | null>(null);
  const [session, setSessionState] = useState<string | null>(null);
  const [show, setShow] = useState<string | null>(null);
  const [playlistId, setPlaylistId] = useState<number | null>(null);
  const [sessions, setSessions] = useState<ReviewSession[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionsError, setSessionsError] = useState<Error | null>(null);
  const [sessionsNonce, setSessionsNonce] = useState(0);

  useEffect(() => {
    if (!available) {
      return;
    }

    const client =
      injectedClient ??
      (CONFIG
        ? createReviewSyncClient({
            brokerURL: CONFIG.brokerURL,
            topic: CONFIG.topic,
            debug: import.meta.env.DEV,
          })
        : null);
    if (!client) {
      return;
    }
    clientRef.current = client;

    const offConnectionState = client.onConnectionStateChange(
      (isConnected, error) => {
        setConnected(isConnected);
        setConnectionError(error ?? null);
      }
    );
    const offFocus = client.subscribe(setFocus);

    if (import.meta.env.DEV) {
      (window as unknown as Record<string, unknown>).__dnaFollowAlong = client;
    }

    return () => {
      offConnectionState();
      offFocus();
      client.disconnect();
      clientRef.current = null;
      setConnected(false);
    };
  }, [available, injectedClient]);

  // The broker connection only exists while a session is being followed, so
  // the indicator reflects "am I following" rather than "is a broker up".
  useEffect(() => {
    const client = clientRef.current;
    if (!client) {
      return;
    }

    client.setSession(session);
    client.setShow(show);

    if (session) {
      client.connect();
    } else {
      client.disconnect();
      setConnected(false);
    }
  }, [available, session, show]);

  useEffect(() => {
    setFocus(null);
    if (playlistId === null) {
      setSessionState(null);
      return;
    }
    setSessionState(localStorage.getItem(sessionStorageKey(playlistId)));
  }, [playlistId]);

  const setSession = useCallback(
    (next: string | null) => {
      const normalized = next?.trim() || null;
      setSessionState(normalized);
      setFocus(null);

      if (playlistId === null) {
        return;
      }
      if (normalized) {
        localStorage.setItem(sessionStorageKey(playlistId), normalized);
      } else {
        localStorage.removeItem(sessionStorageKey(playlistId));
      }
    },
    [playlistId]
  );

  const refreshSessions = useCallback(() => {
    setSessionsNonce((nonce) => nonce + 1);
  }, []);

  useEffect(() => {
    if (!available || !CONFIG?.sessionsUrl || !show) {
      setSessions([]);
      setSessionsError(null);
      return;
    }

    const controller = new AbortController();
    setSessionsLoading(true);

    fetchReviewSessions({
      baseUrl: CONFIG.sessionsUrl,
      show,
      signal: controller.signal,
    })
      .then((result) => {
        setSessions(sortReviewSessions(result));
        setSessionsError(null);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setSessions([]);
        setSessionsError(
          error instanceof Error ? error : new Error('Failed to list sessions')
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setSessionsLoading(false);
        }
      });

    return () => controller.abort();
  }, [available, show, sessionsNonce]);

  return (
    <FollowAlongContext.Provider
      value={{
        available,
        hasSessionDirectory: !!CONFIG?.sessionsUrl,
        connected,
        connectionError,
        sessions,
        sessionsLoading,
        sessionsError,
        refreshSessions,
        session,
        setSession,
        focus,
        show,
        setShow,
        playlistId,
        setPlaylistId,
      }}
    >
      {children}
    </FollowAlongContext.Provider>
  );
}

export function useFollowAlongContext(): FollowAlongContextValue {
  const context = useContext(FollowAlongContext);
  if (!context) {
    throw new Error(
      'useFollowAlongContext must be used within a FollowAlongProvider'
    );
  }
  return context;
}
