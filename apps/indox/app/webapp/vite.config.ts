import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Served by the Flask BFF at the app root (`/`) in production, and embedded
// same-origin in the console under `/a/incoming/`. `base: './'` emits RELATIVE
// hashed asset URLs so they resolve correctly against the document's <base>
// (the console injects `<base href="/a/incoming/">` when embedding) or against
// the root path when accessed standalone. Long-cache `assets/*` (content-hashed).
export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
  },
  server: {
    port: 5174,
    proxy: {
      '/incomingDocuments': 'http://localhost:8080',
    },
  },
});
