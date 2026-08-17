import '@testing-library/jest-dom';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as Record<string, unknown>).ResizeObserver = ResizeObserverMock;

// Providers mounted by the shared test wrapper open sockets on mount. Stub the
// transport so unit tests never reach for a real broker or backend.
class WebSocketMock {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readyState = WebSocketMock.CONNECTING;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: (() => void) | null = null;

  constructor(public url: string) {}

  send() {}

  close() {
    this.readyState = WebSocketMock.CLOSED;
  }

  addEventListener() {}
  removeEventListener() {}
}
(globalThis as Record<string, unknown>).WebSocket = WebSocketMock;

// Cleanup after each test
afterEach(() => {
  cleanup();
});
