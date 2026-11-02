import { defineConfig } from 'vite';

export default defineConfig({
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 6000 },
  server: { proxy: { '/api': 'http://127.0.0.1:8765', '/health': 'http://127.0.0.1:8765' } },
});
