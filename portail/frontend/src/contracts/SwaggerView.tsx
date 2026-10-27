import { useEffect, useRef } from "react";

// Chargé paresseusement par celui qui l'affiche : le bundle Swagger pèse plus que tout
// le reste de l'application réunie, et la plupart des écrans n'en ont jamais besoin.
import SwaggerUI from "swagger-ui-dist/swagger-ui-es-bundle.js";
import "swagger-ui-dist/swagger-ui.css";

/**
 * Le visualiseur Swagger (Gael, 25/10/2026), partagé par les contrats et les sources.
 *
 * Swagger UI n'est pas un composant React : on lui donne un nœud et il s'y installe.
 * D'où la ref et l'effet — React ne le rend pas, il l'héberge, comme l'éditeur JSLT.
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
      // Rien à essayer : les points d'entrée d'ingestion ne sont pas encore hébergés,
      // et un bouton « Try it out » qui échoue ferait croire à une panne.
      supportedSubmitMethods: [],
      deepLinking: false,
    });
  }, [spec]);

  return <div className="swagger-host" ref={host} />;
}
