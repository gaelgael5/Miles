import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { rememberPendingAuthorize } from "./oauth/pendingAuthorize";
import "./i18n/i18n";
import "@miles/socle-web/styles.css";

// Avant tout rendu : une connexion OIDC quittera la page et reviendra sur « / ».
rememberPendingAuthorize();

const root = document.getElementById("root");
if (root === null) {
  throw new Error("élément #root absent de index.html");
}

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={new QueryClient()}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
