import { defineConfig } from "vitest/config";

// Configuración de los tests del frontend. Entorno jsdom (los módulos de las
// vistas tocan el DOM al montarse) y los tests en `tests/`.
export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.js"],
    setupFiles: ["./tests/setup.js"],
    globals: false,
  },
});
