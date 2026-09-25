import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          // دمج مكتبات التفاعل الأساسية في حزمة واحدة
          'vendor-core': ['react', 'react-dom', 'react-router-dom'],
          // دمج الأيقونات في حزمة منفصلة لتخفيف الحجم
          'vendor-icons': ['lucide-react'],
        },
      },
    },
  },
})
