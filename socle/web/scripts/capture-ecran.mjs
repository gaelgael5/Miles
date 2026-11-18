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
 * demandés, à confronter aux valeurs de la maquette), `journal` (ce que la page a dit :
 * exceptions et erreurs de console — à LIRE EN PREMIER devant un écran blanc) et `png`
 * en base64.
 *
 * Les tables de doublures sont à écrire au cas par cas : un écran se peint avec ce que
 * SES routes rendent, et une table générique rendrait des écrans vides qu'on prendrait
 * pour des écrans propres.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ICI = dirname(fileURLToPath(import.meta.url));

/**
 * La fonction exécutée par browserless. Elle ne juge rien : elle rapporte.
 *
 * ATTENTION : c'est un littéral de GABARIT. Un accent grave ou un ${…} dans son corps —
 * commentaires compris — le termine ou l'interpole, et le fichier ne se charge même plus
 * (SyntaxError au premier mot cité). Payé le 18/11/2026 en citant un attribut HTML entre
 * accents graves dans un commentaire.
 */
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
  // Ce que la PAGE dit d'elle-même. Sans ce journal, un écran blanc ne rend que des
  // sélecteurs « absents », et on cherche une faute de sélecteur là où React a planté :
  // une heure perdue le 18/11/2026. Une exception non attrapée démonte tout l'arbre, et
  // c'est son message qui nomme la cause.
  const journal = [];
  page.on("pageerror", (e) => journal.push({ genre: "exception", texte: String(e.message || e) }));
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") {
      journal.push({ genre: m.type(), texte: m.text().slice(0, 300) });
    }
  });
  await page.goto(context.url, { waitUntil: "networkidle2" });
  // Le réseau au repos ne veut pas dire la page peinte : les écrans enchaînent une
  // seconde requête sur la réponse de la première, et React rend après.
  await new Promise((r) => setTimeout(r, 1500));
  // Tous les écrans ne sont pas au bout d'une URL : « Mon profil » s'ouvre par le bouton
  // de la barre du haut, et son état vit dans React. Sans ce clic, on mesurerait l'écran
  // d'accueil en croyant mesurer le profil — et tout y serait juste.
  //
  // Une SÉQUENCE, parce qu'un seul clic ne suffit pas : un écran du menu latéral se
  // trouve au bout de trois replis — le workspace, le groupe « Modèles de données », puis
  // l'entrée elle-même. Les sélecteurs sont joués dans l'ordre, et un sélecteur absent
  // ARRÊTE la capture en le nommant : un clic manqué en silence rendrait l'écran
  // précédent, où tout paraîtrait juste (le piège payé le 18/11/2026 sur « Mon profil »).
  for (const selecteur of context.clics || (context.clic ? [context.clic] : [])) {
    const cible = await page.$(selecteur);
    if (cible === null) {
      return { data: { erreur: "clic_introuvable", selecteur, journal }, type: "application/json" };
    }
    try {
      await cible.click();
    } catch (cause) {
      // Un repli du menu laisse ses enfants DANS le document mais masqués : ils se
      // trouvent au sélecteur et ne se cliquent pas. Sans ce message, browserless rend
      // « Node is either not clickable » sans dire DE QUI il parle, et on cherche le
      // mauvais niveau du menu — mesuré le 18/11/2026.
      return {
        data: { erreur: "clic_impossible", selecteur, journal, cause: String(cause.message || cause) },
        type: "application/json",
      };
    }
    await new Promise((r) => setTimeout(r, 1200));
  }
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
  return { data: { defauts, styles, journal, png }, type: "application/json" };
}
`;

/** Le corps de la batterie, extrait du fichier qui la porte — une seule source. */
export function batterie() {
  const source = readFileSync(join(ICI, "proprete-des-ecrans.js"), "utf-8");
  const marque = "export const BATTERIE = ";
  return source.slice(source.indexOf(marque) + marque.length).trimEnd().replace(/;$/, "");
}

/**
 * Le corps de la requête `POST /function` de browserless.
 *
 * `clic` : sélecteur à cliquer une fois la page peinte, pour un écran qui n'est pas au
 * bout d'une URL (le profil s'ouvre par `.topbar-user`).
 * `clics` : la même chose en SÉQUENCE, pour un écran au bout de plusieurs replis du menu.
 * La réponse porte alors `erreur: "clic_introuvable"` et le `selecteur` fautif si l'un
 * d'eux manque, au lieu de rendre l'écran précédent comme s'il était le bon.
 */
export function charge({ url, table = [], styles = [], largeur = 1280, clic = null, clics = null }) {
  return JSON.stringify({
    code: FONCTION,
    context: { url, table, styles, largeur, clic, clics, batterie: batterie() },
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
