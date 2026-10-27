/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// En dev, le front et l'API partagent la même origine via ce proxy, comme en
// livraison derrière nginx : aucune URL d'API à configurer côté navigateur.
const backendUrl = process.env.MILES_BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  // Travailleurs en modules ES : celui de monaco-yaml se découpe en morceaux, qu'un
  // travailleur « iife » (le format par défaut) ne sait pas charger — Monaco retombait
  // alors sur le fil principal, sans service YAML.
  worker: { format: "es" },
  server: { proxy: { "/api": backendUrl } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
  },
});
