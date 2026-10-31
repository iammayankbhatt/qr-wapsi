import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 127.0.0.1, not localhost: on Windows Node may resolve localhost to ::1 while uvicorn listens on IPv4
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
