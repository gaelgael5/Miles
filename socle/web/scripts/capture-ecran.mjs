/**
 * Ouvrir un écran LIVRÉ dans le vrai Chromium de la machine de test, et le mesurer.
 *
 * `proprete-des-ecrans.js` dit QUOI mesurer et explique pourquoi jsdom n'y suffit pas.
 * Ce fichier-ci est ce qui manquait : de quoi le JOUER. Il a été réécrit de mémoire à
 * chaque séance, et chaque réécriture a repayé les mêmes trois pièges.
 *
 * ## Les trois pièges, pour n'avoir pas à les retrouver
 *
 * 1. **Le cookie de session est `Secure`** : aucune session ne s'ouvre en HTTP depuis
 *    browserless. On double donc `fetch` par `evaluateOnNewDocument` — AVANT tout script
 *    de la page — et on sert des réponses canoniques. Ce qui est éprouvé ainsi est la
 *    FORME de l'écran livré, jamais sa donnée.
 * 2. **Le conteneur ne résout pas le nom d'hôte de la machine.** `http://host-test-37:8080`
 *    rend `ERR_NAME_NOT_RESOLVED` depuis browserless ; l'adresse de la passerelle docker
 *    (`172.17.0.1`) marche. Mesuré le 09/11/2026.
 * 3. **Une route non doublée doit rendre quelque chose**, et pas tomber sur le back-office
 *    réel qui répondra 401 : le repli rend `[]`, ce qui laisse les écrans se peindre vides
 *    plutôt que de rester en erreur.
 *
 * ## Mode d'emploi
 *
 *     node socle/web/scripts/capture-ecran.mjs > /tmp/payload.json
 *     scp /tmp/payload.json test1:/tmp/ && ssh test1 \
 *       'curl -s -X POST http://localhost:3000/function \
 *          -H "Content-Type: application/json" --data-binary @/tmp/payload.json'
 *
 * La réponse porte `defauts` (la batterie), `styles` (les styles CALCULÉS des éléments
 * demandés, à confronter aux valeurs de la maquette) et `png` en base64.
 *
 * Les tables de doublures sont à écrire au cas par cas : un écran se peint avec ce que
 * SES routes rendent, et une table générique rendrait des écrans vides qu'on prendrait
 * pour des écrans propres.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ICI = dirname(fileURLToPath(import.meta.url));

/** La fonction exécutée par browserless. Elle ne juge rien : elle rapporte. */
export const FONCTION = `
export default async function ({ page, context }) {
  await page.setViewport({ width: context.largeur || 1280, height: 1000 });
  await page.evaluateOnNewDocument((table) => {
    const vrai = window.fetch.bind(window);
    window.fetch = async (entree, init) => {
      const url = typeof entree === "string" ? entree : entree.url;
      for (const paire of table) {
        if (url.includes(paire[0])) {
          return new Response(JSON.stringify(paire[1]), {
            status: 200, headers: { "Content-Type": "application/json" } });
        }
      }
      if (url.includes("/api/")) {
        return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return vrai(entree, init);
    };
  }, context.table);
  await page.goto(context.url, { waitUntil: "networkidle2" });
  // Le réseau au repos ne veut pas dire la page peinte : les écrans enchaînent une
  // seconde requête sur la réponse de la première, et React rend après.
  await new Promise((r) => setTimeout(r, 1500));
  const defauts = await page.evaluate("(" + context.batterie + ")()");
  const styles = await page.evaluate((demandes) => {
    const sortie = {};
    for (const [nom, sel, props] of demandes) {
      const el = document.querySelector(sel);
      if (el === null) { sortie[nom] = { absent: sel }; continue; }
      const calcule = getComputedStyle(el);
      const lu = { texte: (el.textContent || "").trim().slice(0, 40) };
      for (const p of props) { lu[p] = calcule.getPropertyValue(p); }
      sortie[nom] = lu;
    }
    return sortie;
  }, context.styles || []);
  const png = await page.screenshot({ fullPage: true, encoding: "base64" });
  return { data: { defauts, styles, png }, type: "application/json" };
}
`;

/** Le corps de la batterie, extrait du fichier qui la porte — une seule source. */
export function batterie() {
  const source = readFileSync(join(ICI, "proprete-des-ecrans.js"), "utf-8");
  const marque = "export const BATTERIE = ";
  return source.slice(source.indexOf(marque) + marque.length).trimEnd().replace(/;$/, "");
}

/** Le corps de la requête `POST /function` de browserless. */
export function charge({ url, table = [], styles = [], largeur = 1280 }) {
  return JSON.stringify({
    code: FONCTION,
    context: { url, table, styles, largeur, batterie: batterie() },
  });
}

// Exemple exécutable : l'écran des workspaces du portail, tel qu'il a servi le 09/11/2026.
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  process.stdout.write(
    charge({
      url: "http://172.17.0.1:8080/",
      table: [
        ["/api/bootstrap/status", { admin_declared: true }],
        [
          "/api/auth/me",
          {
            kind: "local_admin",
            username: "admin",
            subject: "admin",
            email: "admin@exemple.fr",
            directory: null,
            root_admin: true,
          },
        ],
        [
          "/api/workspaces",
          [
            {
              id: "guichet",
              name: "Guichet",
              repo_url: "https://github.com/exemple/miles-guichet.git",
              security_service_id: null,
              work_branch: null,
              default_culture: "fr-FR",
            },
          ],
        ],
      ],
      styles: [
        ["titreOuvrable", "main .row-open", ["color", "font-size", "font-weight"]],
        ["sousTitre", "main .row-sub", ["color", "font-size", "font-family"]],
        // Le STYLE du filet avec sa couleur, et pas la couleur seule : une bordure
        // `none` — la dernière ligne d'une liste — rend `currentColor`, qu'on lirait
        // comme un filet d'encre alors que rien n'est peint.
        [
          "ligne",
          "main .row",
          ["padding-top", "padding-left", "border-bottom-style", "border-bottom-color"],
        ],
      ],
    }),
  );
}
