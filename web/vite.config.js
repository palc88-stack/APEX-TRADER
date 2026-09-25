import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path' // يتطلب تثبيت @types/node إذا كنت تستخدم TypeScript

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  base: '/',
  
  // إعداد اختصارات المسارات (Path Aliases) لتسهيل الاستدعاء في المشروع
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },

  // إعدادات خادم التطوير
  server: {
    port: 3000,
    host: true, // للسماح بالوصول عبر الشبكة المحلية (Local Network)
    open: true, // فتح المتصفح تلقائياً عند تشغيل المشرو
  },

  // إعدادات المعاينة
  preview: {
    port: 4173,
    host: true,
  },

  // إعدادات البناء والتجميع (Build)
  build: {
    outDir: 'dist',
    sourcemap: false,
    emptyOutDir: true,
    chunkSizeWarningLimit: 1000,
    
    // تقسيم الملفات (Code Splitting) لتسريع تحميل الموقع
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom'], // فصل React لمساعدتها على التخزين المؤقت (Caching)
        },
      },
    },
  },
})
