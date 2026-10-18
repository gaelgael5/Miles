/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// En dev, le front et l'API partagent la même origine via ce proxy, comme en
// livraison derrière nginx : aucune URL d'API à configurer côté navigateur.
const backendUrl = process.env.MILES_BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": backendUrl } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
  },
});
