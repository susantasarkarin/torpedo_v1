import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/__tests__/setup.js"],
  },
  build: {
    assetsDir: 'static',
    // Production build optimizations
    target: 'es2020',
    minify: 'esbuild',
    sourcemap: false,
    cssCodeSplit: true,
    // Chunk splitting for better caching
    rollupOptions: {
      output: {
        manualChunks: {
          // Vendor chunk - rarely changes, cached long-term
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-ui': ['@radix-ui/react-dialog', '@radix-ui/react-popover', '@radix-ui/react-select', '@radix-ui/react-tabs', '@radix-ui/react-tooltip'],
          'vendor-charts': ['recharts'],
          'vendor-forms': ['react-hook-form'],
          'vendor-utils': ['date-fns', 'dompurify', 'clsx'],
        },
      },
    },
    // Increase chunk size warning limit (split chunks are expected)
    chunkSizeWarningLimit: 600,
  },
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
