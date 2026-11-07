import { ContractAddress } from "@miles/socle-web";

import { contractUrl } from "../api/ingestion";
import { ContractCurl } from "./ContractCurl";
import { ContractGate } from "./ContractGate";

/**
 * Ce qu'on DONNE à l'intégrateur : l'adresse publique du contrat, et de quoi appeler.
 *
 * **Le visualiseur Swagger est dans son propre onglet depuis le 07/11/2026** (Gael :
 * « passe le swagger dans un onglet séparé »). Il pesait quatre cents pixels de prose
 * avant la première ligne utile, et ce qu'on vient chercher ici — l'adresse, la commande
 * à coller — se lisait après avoir fait défiler le document entier. Même forme que le
 * portail, qui a son `SwaggerScreen` à part depuis le premier jour.
 */
export function SourceContract({ source }: { source: string }) {
  return (
    <ContractGate source={source}>
      {() => (
        <>
          <ContractAddress url={contractUrl(source)} filename={`${source}.openapi.json`} />
          <ContractCurl source={source} />
        </>
      )}
    </ContractGate>
  );
}
