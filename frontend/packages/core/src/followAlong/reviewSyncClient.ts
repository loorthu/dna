import { Client } from '@stomp/stompjs';
import { parseCurrentClip } from './parseCurrentClip';
import type {
  ReviewConnectionStateCallback,
  ReviewFocus,
  ReviewFocusCallback,
  ReviewFocusParser,
} from './types';

/**
 * How long a clip must be the latest announcement before it is reported.
 *
 * The player rebroadcasts continuously and more than one publisher can announce
 * under the same session name, so announcements arrive in bursts. Settling
 * briefly keeps a rapid burst from being reported as several changes. It is
 * deliberately short: this drives a hint, and a late hint is worth less than a
 * slightly noisy one.
 */
const DEFAULT_SETTLE_MS = 1500;

export interface ReviewSyncClientConfig {
  /** STOMP-over-WebSocket broker, e.g. `ws://broker.example.com:61614/stomp`. */
  brokerURL: string;
  /** Topic the review player broadcasts on. */
  topic: string;
  login?: string;
  passcode?: string;
  reconnectDelay?: number;
  heartbeatIncoming?: number;
  heartbeatOutgoing?: number;
  debug?: boolean;
  /** Swap in when the player's payload is not the default XML shape. */
  parse?: ReviewFocusParser;
  /** Overrides {@link DEFAULT_SETTLE_MS}; 0 reports every announcement. */
  settleMs?: number;
}

function normalize(value: string | null | undefined): string {
  return value?.trim().toLowerCase() ?? '';
}

/**
 * Whether two announcements point at the same thing as far as a subscriber is
 * concerned. Compared on the clip id rather than the whole focus: the player
 * may re-announce the same clip with a different internal handle, and that is
 * not a change anyone downstream can see.
 */
function sameClip(a: ReviewFocus, b: ReviewFocus): boolean {
  return a.externalRef === b.externalRef;
}

/**
 * Listens to a review player's broadcast topic and reports the clip currently
 * on screen in one chosen session.
 *
 * The topic is shared by every session of every show, so subscribers only hear
 * about messages matching both the selected session and show.
 *
 * Deliberately mirrors `DNAEventClient`: `connect`/`disconnect`/`subscribe`/
 * `onConnectionStateChange`.
 */
export class ReviewSyncClient {
  private config: ReviewSyncClientConfig;
  private client: Client | null = null;
  private parse: ReviewFocusParser;
  private focusCallbacks: Set<ReviewFocusCallback> = new Set();
  private connectionStateCallbacks: Set<ReviewConnectionStateCallback> =
    new Set();
  private _isConnected = false;
  private _connectionError: Error | null = null;
  private _session: string | null = null;
  private _show: string | null = null;
  private _lastFocus: ReviewFocus | null = null;
  private settleTimer: ReturnType<typeof setTimeout> | null = null;
  private pending: ReviewFocus | null = null;

  constructor(config: ReviewSyncClientConfig) {
    this.config = config;
    this.parse = config.parse ?? parseCurrentClip;
  }

  get isConnected(): boolean {
    return this._isConnected;
  }

  get connectionError(): Error | null {
    return this._connectionError;
  }

  get session(): string | null {
    return this._session;
  }

  get show(): string | null {
    return this._show;
  }

  get lastFocus(): ReviewFocus | null {
    return this._lastFocus;
  }

  connect(): void {
    if (this.client) {
      return;
    }

    const client = new Client({
      brokerURL: this.config.brokerURL,
      connectHeaders: {
        login: this.config.login ?? '',
        passcode: this.config.passcode ?? '',
      },
      reconnectDelay: this.config.reconnectDelay ?? 5000,
      heartbeatIncoming: this.config.heartbeatIncoming ?? 10000,
      heartbeatOutgoing: this.config.heartbeatOutgoing ?? 10000,
      debug: this.config.debug
        ? (message: string) => console.log('[ReviewSyncClient]', message)
        : () => {},
    });

    client.onConnect = () => {
      this._isConnected = true;
      this._connectionError = null;
      this.notifyConnectionState(true);
      client.subscribe(this.config.topic, (message) => {
        this.handleFrameBody(message.body);
      });
      if (this.config.debug) {
        console.log('[ReviewSyncClient] Connected to', this.config.brokerURL);
      }
    };

    client.onStompError = (frame) => {
      this.fail(new Error(frame.headers['message'] ?? 'STOMP protocol error'));
    };

    client.onWebSocketError = () => {
      this.fail(new Error('Review sync connection failed'));
    };

    client.onWebSocketClose = () => {
      if (this._isConnected) {
        this._isConnected = false;
        this.notifyConnectionState(false);
      }
    };

    this.client = client;
    client.activate();
  }

  disconnect(): void {
    const client = this.client;
    this.client = null;
    this._isConnected = false;
    this.clearSettle();

    if (client) {
      void client.deactivate();
    }
  }

  /**
   * Feeds one raw broadcast payload through the filter, as the topic
   * subscription does. Public so tests and the browser console can drive the
   * client without a broker.
   */
  handleFrameBody(body: string): void {
    const focus = this.parse(body);
    if (!focus || !this.matchesFilter(focus)) {
      return;
    }

    // Already reporting this clip: the player is just repeating itself.
    if (this._lastFocus && sameClip(this._lastFocus, focus)) {
      this.clearSettle();
      return;
    }

    const settleMs = this.config.settleMs ?? DEFAULT_SETTLE_MS;
    if (settleMs <= 0) {
      this.emit(focus);
      return;
    }

    this.pending = focus;
    if (this.settleTimer) {
      return;
    }
    this.settleTimer = setTimeout(() => {
      this.settleTimer = null;
      const settled = this.pending;
      this.pending = null;
      if (settled && !(this._lastFocus && sameClip(this._lastFocus, settled))) {
        this.emit(settled);
      }
    }, settleMs);
  }

  private emit(focus: ReviewFocus): void {
    this._lastFocus = focus;
    this.focusCallbacks.forEach((callback) => {
      try {
        callback(focus);
      } catch (err) {
        console.error('[ReviewSyncClient] Error in focus callback:', err);
      }
    });
  }

  private clearSettle(): void {
    if (this.settleTimer) {
      clearTimeout(this.settleTimer);
      this.settleTimer = null;
    }
    this.pending = null;
  }

  private matchesFilter(focus: ReviewFocus): boolean {
    if (!this._session) {
      return false;
    }
    if (normalize(focus.session) !== normalize(this._session)) {
      return false;
    }
    if (this._show && normalize(focus.show) !== normalize(this._show)) {
      return false;
    }
    return true;
  }

  private fail(error: Error): void {
    this._isConnected = false;
    this._connectionError = error;
    this.notifyConnectionState(false, error);
    if (this.config.debug) {
      console.error('[ReviewSyncClient]', error.message);
    }
  }

  setSession(session: string | null): void {
    if (normalize(session) === normalize(this._session)) {
      return;
    }
    this._session = session;
    this.forget();
  }

  setShow(show: string | null): void {
    if (normalize(show) === normalize(this._show)) {
      return;
    }
    this._show = show;
    this.forget();
  }

  private forget(): void {
    this._lastFocus = null;
    this.clearSettle();
  }

  subscribe(callback: ReviewFocusCallback): () => void {
    this.focusCallbacks.add(callback);
    return () => {
      this.focusCallbacks.delete(callback);
    };
  }

  onConnectionStateChange(callback: ReviewConnectionStateCallback): () => void {
    this.connectionStateCallbacks.add(callback);
    return () => {
      this.connectionStateCallbacks.delete(callback);
    };
  }

  private notifyConnectionState(connected: boolean, error?: Error): void {
    this.connectionStateCallbacks.forEach((callback) => {
      try {
        callback(connected, error);
      } catch (err) {
        console.error(
          '[ReviewSyncClient] Error in connection state callback:',
          err
        );
      }
    });
  }
}

export function createReviewSyncClient(
  config: ReviewSyncClientConfig
): ReviewSyncClient {
  return new ReviewSyncClient(config);
}
