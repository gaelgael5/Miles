/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Aucune cible de construction : le socle n'est pas une application et ne produit pas de
// bundle. Cette configuration ne sert qu'à vitest, pour que le socle soit éprouvé SEUL —
// comme socle/python l'est par son propre pytest. Les mêmes tests retournent ensuite dans
// le contexte de chaque produit, où ils vérifient autre chose : que le câblage y tient.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
  },
});
