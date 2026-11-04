import { useEffect, useRef } from "react";

// Chargé paresseusement par celui qui l'affiche : le bundle Swagger pèse plus que tout
// le reste de l'application réunie, et aucun autre écran n'en a besoin.
import SwaggerUI from "swagger-ui-dist/swagger-ui-es-bundle.js";
import "swagger-ui-dist/swagger-ui.css";

/**
 * Le visualiseur Swagger du contrat d'une source (Gael, 04/11/2026 : « il faut que
 * l'onglet swagger reprenne un composant standard d'affichage swagger »).
 *
 * Jumeau de celui du portail, et c'est une duplication ASSUMÉE : trente lignes contre un
 * paquet tiers lourd à faire entrer dans `socle/web`, que les trois produits
 * installeraient — le module d'enrôlement compris, qui n'affiche aucun contrat. La
 * mutualisation est un geste à part, à décider pour elle-même.
 *
 * Swagger UI n'est pas un composant React : on lui donne un nœud et il s'y installe.
 * D'où la ref et l'effet — React ne le rend pas, il l'héberge.
 *
 * On lui passe le document DÉJÀ lu (`spec`) et jamais une URL : Miles sert ses documents
 * derrière la session, et Swagger ne porterait pas le cookie sur une requête qu'il
 * émettrait lui-même.
 */
export default function SwaggerView({ spec }: { spec: object }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (host.current === null) {
      return;
    }
    SwaggerUI({
      domNode: host.current,
      spec,
      // Rien à essayer ICI, et ce n'est pas un oubli : le dépôt exige une clé d'API, qui
      // ne descend jamais jusqu'au navigateur. Un « Try it out » partirait donc sans clé
      // et rendrait 401, qu'on lirait comme un refus du point d'entrée. L'essai qui
      // dépose pour de vrai est dans l'onglet voisin, avec la clé du back-office.
      supportedSubmitMethods: [],
      deepLinking: false,
    });
  }, [spec]);

  return <div className="swagger-host" ref={host} />;
}
