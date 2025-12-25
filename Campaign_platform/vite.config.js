import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Proxy CPX callback to backend
      '/cpx-response': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
