import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return undefined
          }

          if (id.includes('react-pdf') || id.includes('pdfjs-dist')) {
            return 'pdf-runtime'
          }

          if (id.includes('react-router') || id.includes('axios') || id.includes('zustand')) {
            return 'app-vendor'
          }

          if (id.includes('react') || id.includes('react-dom')) {
            return 'react-core'
          }

          if (id.includes('lucide-react')) {
            return 'ui-icons'
          }

          return 'vendor'
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8001',
        changeOrigin: true,
        ws: true,
      },
      '/health': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
})
