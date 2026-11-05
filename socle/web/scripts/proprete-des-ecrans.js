/**
 * La batterie de propreté des écrans — à rejouer dans un VRAI navigateur.
 *
 * Elle ne juge rien : elle mesure. jsdom ne calcule aucun rectangle, donc aucune suite
 * de tests ne peut voir un titre collé à son contenu, une colonne d'étiquettes large
 * d'un quart de la carte, ou deux textes imprimés l'un sur l'autre. Ces trois familles
 * sont arrivées pour de vrai (LESSONS.md, entrée « frontend »).
 *
 * Mode d'emploi : construire le front, le servir, puis dans le Chromium de la machine de
 * test (`POST /function` de browserless) ouvrir chaque entrée du menu et évaluer
 * `BATTERIE` sur la page. Doubler `window.fetch` par `page.evaluateOnNewDocument` : le
 * cookie de session est `Secure`, aucune session ne s'ouvre en HTTP depuis browserless.
 *
 * Un défaut rendu ici n'est pas une condamnation — le seuil est arbitraire, pas la
 * mesure. C'est une ligne à aller REGARDER.
 */
export const BATTERIE = () => {
  const defauts = [];
  const texte = (el) => (el.textContent || "").trim().replace(/\s+/g, " ");
  const dit = (quoi, quoi2) => defauts.push({ quoi, ...quoi2 });

  // A. Un titre de carte collé à son contenu : zéro n'est jamais une valeur voulue.
  for (const carte of document.querySelectorAll(".card, .card-inset")) {
    const tete = carte.querySelector(".card-head");
    const suivant = tete === null ? null : tete.nextElementSibling;
    if (suivant === null) { continue; }
    const ecart = suivant.getBoundingClientRect().top - tete.getBoundingClientRect().bottom;
    if (ecart < 8) { dit("titre-colle", { ecart: Math.round(ecart), ou: texte(tete).slice(0, 40) }); }
  }

  // B. Une étiquette qui est une PHRASE fixe à elle seule la largeur de la colonne.
  for (const dl of document.querySelectorAll(".facts")) {
    const hote = dl.closest(".card, .card-inset, .split-detail") ?? dl.parentElement;
    const dts = [...dl.querySelectorAll("dt")];
    if (dts.length === 0) { continue; }
    const large = Math.max(...dts.map((d) => d.getBoundingClientRect().width));
    const part = large / hote.getBoundingClientRect().width;
    const plusLongue = dts.map(texte).sort((a, b) => b.length - a.length)[0];
    if (part > 0.22) { dit("etiquette-phrase", { part: Math.round(part * 100), etiquette: plusLongue }); }
  }

  // C. Le chapeau répété dans le contenu : une information, un endroit.
  const chapeau = document.querySelector(".lead");
  if (chapeau !== null) {
    const l = texte(chapeau);
    for (const dd of document.querySelectorAll("main .facts dd, main .value")) {
      const v = texte(dd);
      if (v.length > 4 && l.includes(v)) { dit("repete-le-chapeau", { valeur: v }); }
    }
  }

  // D. Deux textes imprimés l'un sur l'autre (le balayage du 28/10, racine `main`).
  const feuilles = [...document.querySelectorAll("main *")]
    .filter((e) => e.children.length === 0 && texte(e) !== "");
  for (let i = 0; i < feuilles.length; i += 1) {
    for (let j = i + 1; j < feuilles.length; j += 1) {
      const a = feuilles[i].getBoundingClientRect();
      const b = feuilles[j].getBoundingClientRect();
      const inter = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left))
        * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
      if (inter > 6) { dit("chevauchement", { a: texte(feuilles[i]).slice(0, 30), b: texte(feuilles[j]).slice(0, 30) }); }
    }
  }

  // E. Un débordement horizontal : la page pousse une barre que personne ne veut.
  const contenu = document.querySelector("main");
  if (contenu !== null && contenu.scrollWidth > contenu.clientWidth + 1) {
    dit("deborde", { de: contenu.scrollWidth - contenu.clientWidth });
  }

  // F. Une ligne de colonnes qui s'est repliée : le `top` le dit en un nombre.
  for (const ligne of document.querySelectorAll(".row-columns")) {
    const tops = [...ligne.children].map((c) => c.getBoundingClientRect().top);
    const ecart = Math.max(...tops) - Math.min(...tops);
    if (tops.length > 1 && ecart > 6) { dit("colonne-repliee", { ecart: Math.round(ecart) }); }
  }

  // G. Une étiquette en capitales qui est une phrase, partout ailleurs que dans `.facts`.
  for (const cap of document.querySelectorAll("main .caption")) {
    const t = texte(cap);
    if (t.length > 28 && cap.closest(".facts") === null) { dit("caption-longue", { etiquette: t }); }
  }

  // H. Une valeur fautive rendue telle quelle : la panne se lit dans l'écran.
  const fautifs = ["undefined", "NaN", "Invalid Date", "[object Object]", "null"];
  for (const el of document.querySelectorAll("main *")) {
    if (el.children.length !== 0) { continue; }
    const t = texte(el);
    for (const mot of fautifs) {
      if (t === mot || t.includes(" " + mot) || t.startsWith(mot + " ")) { dit("valeur-fautive", { texte: t.slice(0, 60) }); }
    }
  }

  // I. Un texte TRONQUÉ par sa boîte : on ne peut pas le lire en entier.
  for (const el of document.querySelectorAll("main *")) {
    if (el.children.length !== 0 || texte(el) === "") { continue; }
    if (el.scrollWidth > el.clientWidth + 2 && getComputedStyle(el).overflow !== "visible") {
      dit("texte-tronque", { texte: texte(el).slice(0, 40) });
    }
  }

  // J. Le MÊME geste offert deux fois : deux boutons de même libellé laissent croire
  // à deux effets (la leçon du renvoi d'ordre, 05/11/2026).
  const gestes = {};
  for (const b of document.querySelectorAll("main button")) {
    const t = texte(b);
    if (t !== "") { gestes[t] = (gestes[t] ?? 0) + 1; }
  }
  for (const [t, n] of Object.entries(gestes)) {
    if (n > 1 && document.querySelectorAll("main .rows li, main .plain-list li").length === 0) {
      dit("geste-en-double", { bouton: t, fois: n });
    }
  }

  // K. Le même texte écrit deux fois dans la page, hors tableaux et listes.
  const vus = {};
  for (const el of document.querySelectorAll("main p, main dd, main dt, main h2, main h3, main .value, main .caption")) {
    if (el.closest("li, .row, .facts-table") !== null) { continue; }
    const t = texte(el);
    if (t.length > 8) { vus[t] = (vus[t] ?? 0) + 1; }
  }
  for (const [t, n] of Object.entries(vus)) {
    if (n > 1) { dit("texte-repete", { texte: t.slice(0, 60), fois: n }); }
  }
  return defauts;
};
