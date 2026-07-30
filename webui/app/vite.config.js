import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api/cp': {
        target: 'http://localhost:4839',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/cp/, '')
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets'
  }
})
