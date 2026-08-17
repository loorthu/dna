import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';
import path from 'path';

// https://vite.dev/config/
// Follow Along's session directory is a separate service that sends no CORS
// headers, so the browser can only read it same-origin. In production nginx
// maps /review-sessions to it (see frontend/default.conf.template); this is the
// dev-server equivalent, enabled by pointing REVIEW_SESSIONS_URL at one.
const reviewSessionsUrl = process.env.REVIEW_SESSIONS_URL?.trim();

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@dna/core': path.resolve(__dirname, '../core/src'),
    },
  },
  server: reviewSessionsUrl
    ? {
        proxy: {
          '/review-sessions': {
            target: reviewSessionsUrl,
            changeOrigin: true,
            rewrite: (p) => p.replace(/^\/review-sessions/, ''),
          },
        },
      }
    : undefined,
});
