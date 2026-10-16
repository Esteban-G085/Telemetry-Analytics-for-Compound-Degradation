import { defineConfig } from "vite";

// En desarrollo el backend FastAPI corre en 127.0.0.1:8000 y Vite hace de proxy,
// de modo que el frontend siempre habla con rutas relativas (/api, /ws).
const BACKEND = "http://127.0.0.1:8000";

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/health": { target: BACKEND, changeOrigin: true },
      "/ws": { target: BACKEND.replace("http", "ws"), ws: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
