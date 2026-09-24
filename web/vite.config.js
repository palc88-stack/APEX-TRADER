// vite.config.js - نسخة Cloudflare الصحيحة
import { defineConfig } from \'vite\'
import react from \'@vitejs/plugin-react\'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: \'dist\',
    sourcemap: false,
    minify: \'esbuild\',
    chunkSizeWarningLimit: 1000
  },
  server: {
    port: 5173,
    host: true
  },
  preview: {
    port: 4173
  }
})
