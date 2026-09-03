import {
  createContext,
  useContext,
  useEffect,
  useState,
  useRef,
  useCallback,
  type ReactNode,
} from 'react';
import {
  DNAEventClient,
  createEventClient,
  setDefaultEventClient,
  type EventType,
  type DNAEvent,
  type EventCallback,
} from '@dna/core';
import { basePath } from '../basePath';

export type { EventType, DNAEvent, EventCallback };

interface EventContextValue {
  client: DNAEventClient | null;
  isConnected: boolean;
  connectionError: Error | null;
  subscribe: <T = unknown>(
    eventType: EventType,
    callback: EventCallback<T>
  ) => () => void;
}

const EventContext = createContext<EventContextValue | null>(null);

// When VITE_WS_URL is unset, derive it from the page origin so the WebSocket
// hits the same host that served the app (e.g. an nginx reverse-proxy that
// forwards /ws to the backend). Falls back to localhost for `vite` dev.
//
// basePath() carries its own trailing slash and is "/" unless the app is mounted under a prefix,
// so this is byte-identical to `${host}/ws` for a root-served deployment. VITE_WS_URL, when set,
// is passed to `new WebSocket()` verbatim and so must stay an absolute URL — it cannot be made
// base-aware, which is the reason the deployments that need a prefix leave it empty.
const WEBSOCKET_URL =
  import.meta.env.VITE_WS_URL ||
  (typeof window !== 'undefined' && window.location.host
    ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}${basePath()}ws`
    : 'ws://localhost:8000/ws');

interface EventProviderProps {
  children: ReactNode;
}

export function EventProvider({ children }: EventProviderProps) {
  const [isConnected, setIsConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<Error | null>(null);
  const clientRef = useRef<DNAEventClient | null>(null);

  useEffect(() => {
    const client = createEventClient({
      wsURL: WEBSOCKET_URL,
      debug: import.meta.env.DEV,
    });

    clientRef.current = client;
    setDefaultEventClient(client);

    const unsubscribe = client.onConnectionStateChange((connected, error) => {
      setIsConnected(connected);
      setConnectionError(error ?? null);
    });

    client.connect();

    return () => {
      unsubscribe();
      client.disconnect();
      clientRef.current = null;
    };
  }, []);

  const subscribe = useCallback(
    <T = unknown,>(
      eventType: EventType,
      callback: EventCallback<T>
    ): (() => void) => {
      if (!clientRef.current) {
        return () => {};
      }
      return clientRef.current.subscribe<T>(eventType, callback);
    },
    []
  );

  return (
    <EventContext.Provider
      value={{
        client: clientRef.current,
        isConnected,
        connectionError,
        subscribe,
      }}
    >
      {children}
    </EventContext.Provider>
  );
}

export function useEventContext(): EventContextValue {
  const context = useContext(EventContext);
  if (!context) {
    throw new Error('useEventContext must be used within an EventProvider');
  }
  return context;
}

export function useEventClient(): DNAEventClient | null {
  const { client } = useEventContext();
  return client;
}
