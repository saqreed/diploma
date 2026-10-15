import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const backend = process.env.DIPLOMA_UI_API_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {host: '127.0.0.1', port: 5173, strictPort: true, proxy: {'/api': backend, '/health': backend}},
  preview: {host: '127.0.0.1', port: 5173, strictPort: true, proxy: {'/api': backend, '/health': backend}},
})
