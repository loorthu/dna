import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';
import path from 'path';

// https://vite.dev/config/
// Follow Along's session directory is a separate service that sends no CORS
// headers, so the browser can only read it same-origin. In production nginx
// maps /review-sessions to it (see frontend/default.conf.template); this is the
// dev-server equivalent, enabled by pointing REVIEW_SESSIONS_URL at one.
const reviewSessionsUrl = process.env.REVIEW_SESSIONS_URL?.trim();

// Archived meeting recordings. In production nginx aliases /recordings/ straight onto the share
// (same file, same Range handling, no proxy hop) and the player is a plain <video src>. The API
// returns that path, so the dev server has to answer it too or every media_url 404s and the
// Recording tab can only ever be tested on the prod host.
//
// A proxy rather than a static mount on purpose: point it at something that serves the archive
// directory the way prod does — Range requests included, since seeking to a cut's in-point is the
// whole feature. Unset leaves the route unhandled, exactly as before.
const recordingsUrl = process.env.RECORDINGS_URL?.trim();

const proxy: Record<string, unknown> = {};
if (reviewSessionsUrl) {
  proxy['/review-sessions'] = {
    target: reviewSessionsUrl,
    changeOrigin: true,
    rewrite: (p: string) => p.replace(/^\/review-sessions/, ''),
  };
}
if (recordingsUrl) {
  // No rewrite: the path is kept whole so the target sees /recordings/<file>, which is what the
  // prod nginx location matches. Keeping them identical means a URL that works here works there.
  proxy['/recordings'] = {
    target: recordingsUrl,
    changeOrigin: true,
  };
}

// Where the app is served from. Root unless a site mounts it under a prefix (SPI serves it at
// /dna/ beside its other tools); Vite rewrites every asset URL with this and re-exposes it as
// import.meta.env.BASE_URL, which src/basePath.ts reads so there is only ever one value.
const base = process.env.VITE_BASE_PATH?.trim() || '/';

export default defineConfig({
  base,
  plugins: [react()],
  resolve: {
    alias: {
      '@dna/core': path.resolve(__dirname, '../core/src'),
    },
  },
  server: Object.keys(proxy).length > 0 ? { proxy } : undefined,
});
