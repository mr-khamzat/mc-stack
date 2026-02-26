import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/rack/',
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
  },
  server: {
    proxy: {
      '/rack/api': {
        target: 'http://localhost:8000',
        rewrite: (path) => path.replace(/^\/rack\/api/, '/api'),
      },
    },
  },
})
