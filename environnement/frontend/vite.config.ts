/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// En dev, le front et l'API partagent la même origine via ce proxy, comme en
// livraison derrière nginx : aucune URL d'API à configurer côté navigateur.
const backendUrl = process.env.MILES_BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  // Le socle web arrive par une dépendance de chemin : son code est résolu à son
  // emplacement réel, HORS de node_modules du produit, et ses imports de react s'y
  // résoudraient donc dans SON node_modules — deux copies de React dans la page, et
  // « Invalid hook call » au premier rendu. `dedupe` force une seule instance.
  // Ne pas retirer : la panne ne se voit pas à la construction, seulement à l'exécution.
  resolve: { dedupe: ["react", "react-dom", "i18next", "react-i18next", "@tanstack/react-query"] },
  server: { proxy: { "/api": backendUrl } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
  },
});
