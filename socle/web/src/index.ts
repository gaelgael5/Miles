/**
 * Surface publique du socle web : un seul point d'entrée pour les produits.
 *
 * Un tonneau unique plutôt qu'une entrée par module : les produits écrivent
 * `from "@miles/socle-web"` et rien d'autre, ce qui rend la frontière lisible d'un coup
 * d'œil dans leurs imports — et vérifiable par le test d'architecture de `tests/`.
 * Les feuilles de style et la doublure de `fetch` des tests ont leurs propres entrées
 * déclarées dans `package.json` : ce ne sont pas des modules TypeScript.
 */
export * from "./api/http";
export * from "./api/auth";
export * from "./api/preferences";
export * from "./api/cultures";
export * from "./api/oidc";
export * from "./api/secrets";
export * from "./api/health";
export * from "./auth/AuthGate";
export * from "./auth/BootstrapScreen";
export * from "./auth/LoginScreen";
export * from "./auth/visitorCulture";
export * from "./i18n/i18n";
// `export *` ne transporte pas l'export par défaut : l'instance i18next partagée est
// nommée ici, parce qu'un produit en a besoin pour changer de langue dans ses tests.
export { default as i18n } from "./i18n/i18n";
export * from "./layout/Topbar";
export * from "./layout/PageHead";
export * from "./layout/ConfirmDialog";
export * from "./layout/CopyButton";
export * from "./cultures/CulturesScreen";
export * from "./oidc/ConnectorsScreen";
export * from "./oidc/ConnectorForm";
export * from "./secrets/SecretsScreen";
export * from "./secrets/SecretCreateForm";
export * from "./secrets/SecretPicker";
export * from "./health/HealthStatus";
export * from "./profile/ProfileShell";
