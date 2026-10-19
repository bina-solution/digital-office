import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';
// Sim build: EVERYTHING (JS+CSS+assets) inlined into one index.html, no network, no chunks.
export default defineConfig({
  base: './',
  plugins: [react(), viteSingleFile()],
  build: { outDir: 'dist-sim', emptyOutDir: true, sourcemap: false, cssCodeSplit: false,
    assetsInlineLimit: 100000000,
    rollupOptions: { output: { inlineDynamicImports: true } } },
});
