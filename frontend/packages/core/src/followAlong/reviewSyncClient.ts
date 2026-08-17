import { Client } from '@stomp/stompjs';
import { parseCurrentClip } from './parseCurrentClip';
import type {
  ReviewConnectionStateCallback,
  ReviewFocus,
  ReviewFocusCallback,
  ReviewFocusParser,
} from './types';

/** Announcements kept so a clip can be resolved without awaiting a rebroadcast. */
const RECENT_CLIP_LIMIT = 16;

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
}

function normalize(value: string | null | undefined): string {
  return value?.trim().toLowerCase() ?? '';
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
  private _expectedClipRef: string | null = null;
  private unknownClipCallbacks: Set<ReviewFocusCallback> = new Set();
  private recentByClipRef: Map<string, ReviewFocus> = new Map();

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

    this.remember(focus);

    // More than one publisher can announce under the same session name, so a
    // frame that clears the session filter is not necessarily the clip the
    // room is on. Hand it to whoever can arbitrate instead of acting on it.
    if (!this.matchesClip(focus)) {
      this.unknownClipCallbacks.forEach((callback) => {
        try {
          callback(focus);
        } catch (err) {
          console.error(
            '[ReviewSyncClient] Error in unknown clip callback:',
            err
          );
        }
      });
      return;
    }

    this.emit(focus);
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

  private remember(focus: ReviewFocus): void {
    if (!focus.clipRef) {
      return;
    }
    this.recentByClipRef.delete(focus.clipRef);
    this.recentByClipRef.set(focus.clipRef, focus);
    while (this.recentByClipRef.size > RECENT_CLIP_LIMIT) {
      const oldest = this.recentByClipRef.keys().next().value;
      if (oldest === undefined) {
        break;
      }
      this.recentByClipRef.delete(oldest);
    }
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

  private matchesClip(focus: ReviewFocus): boolean {
    // With nothing to arbitrate against, every announcement for the session is
    // taken at face value — the behaviour of a site with no session directory.
    if (!this._expectedClipRef || !focus.clipRef) {
      return true;
    }
    return focus.clipRef === this._expectedClipRef;
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

  /**
   * Names the clip the followed session is really on, from the session
   * directory. Announcements for any other clip are withheld.
   *
   * When the named clip has already been announced, it is emitted straight
   * away rather than waiting for the player to repeat itself — the arbitration
   * costs a directory round trip, not a rebroadcast interval.
   */
  setExpectedClipRef(clipRef: string | null): void {
    const next = clipRef?.trim() || null;
    if (next === this._expectedClipRef) {
      return;
    }
    this._expectedClipRef = next;

    if (!next) {
      return;
    }
    const known = this.recentByClipRef.get(next);
    if (known && known !== this._lastFocus) {
      this.emit(known);
    }
  }

  get expectedClipRef(): string | null {
    return this._expectedClipRef;
  }

  /**
   * Notified when the session announces a clip that is not the expected one —
   * the cue to re-read the session directory, since the room may have moved.
   */
  onUnknownClip(callback: ReviewFocusCallback): () => void {
    this.unknownClipCallbacks.add(callback);
    return () => {
      this.unknownClipCallbacks.delete(callback);
    };
  }

  private forget(): void {
    this._lastFocus = null;
    this._expectedClipRef = null;
    this.recentByClipRef.clear();
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
