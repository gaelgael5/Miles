import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.strict],
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Une date formatée sans culture explicite prend celle du NAVIGATEUR, pas celle de
      // l'interface : le 2 novembre s'affichait « 11/2/2026 » en français, lisible et FAUX
      // (bug 4f53012d). La correction ne tient que si elle ne peut pas être défaite écran
      // par écran — six l'avaient déjà, sur trois produits. Le seul appel toléré est dans
      // `src/i18n/instants.ts`, qui porte sa dérogation et sa raison.
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "CallExpression[callee.property.name=/^toLocale(String|DateString|TimeString)$/]",
          message:
            "Formate les instants avec useInstant() (i18n/instants.ts) : toLocaleString() emploie la culture du NAVIGATEUR, pas celle de l'interface (bug 4f53012d).",
        },
      ],
    },
  },
);
