import { ApiError } from "@miles/socle-web";

/** Où en est l'envoi : octets partis, octets à envoyer. */
export interface UploadProgress {
  sent: number;
  total: number;
}

/** Levée quand l'envoi a été interrompu par l'écran, et non par une panne. */
export class UploadAborted extends Error {
  constructor() {
    super("envoi interrompu");
  }
}

/**
 * Envoie un fichier en RAPPORTANT sa progression, et rend la réponse décodée.
 *
 * **`XMLHttpRequest` et non `fetch`, délibérément.** `fetch()` ne rapporte pas la
 * progression d'un ENVOI : il n'expose que le corps de la réponse en flux, jamais celui de
 * la requête. Seul `XMLHttpRequest.upload` émet des `progress`. Ce n'est donc pas une
 * vieillerie à moderniser : remplacer ceci par `fetch` ferait disparaître la barre sans
 * qu'aucun test de type ni aucun appel n'échoue, et l'écran redeviendrait muet pendant les
 * minutes d'un envoi — ce qui est exactement le défaut que Gael a signalé le 07/11/2026
 * (« je n'en vois pas la fin. soit parce que c est tres long soit parce que ca plante »).
 *
 * **Ce n'est pas un écart à la règle « tout appel API passe par TanStack Query »** : cette
 * fonction rend une promesse et vit dans une `mutationFn`, donc l'état de l'appel reste
 * celui de la mutation. Ce qu'elle remplace est le transport, pas la gestion d'état.
 *
 * Le `File` est passé TEL QUEL : le navigateur le lit depuis le disque au fil de l'envoi.
 * Le lire en JavaScript avant (`file.text()`, un `JSON.parse` de contrôle) chargerait le
 * document entier dans l'onglet — neuf cents mégaoctets pour celui de Gael — et le
 * contrôle du contenu est de toute façon le travail du point d'entrée, dont les refus sont
 * précisément ce que l'essai sert à montrer.
 *
 * Les erreurs sont celles du dépôt : `ApiError` porte le statut et le `detail` du refus,
 * comme `request()` du socle, pour que les écrans n'aient pas deux formes à lire.
 */
export function uploadWithProgress<T>(
  path: string,
  file: File,
  contentType: string,
  onProgress: (progress: UploadProgress) => void,
  signal?: AbortSignal,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const envoi = new XMLHttpRequest();
    envoi.open("POST", path);
    envoi.setRequestHeader("Content-Type", contentType);

    envoi.upload.addEventListener("progress", (event) => {
      // `lengthComputable` est faux tant que la taille n'est pas connue : rapporter zéro
      // sur zéro ferait afficher une barre à 100 % avant le premier octet.
      if (event.lengthComputable) {
        onProgress({ sent: event.loaded, total: event.total });
      }
    });
    envoi.addEventListener("load", () => {
      const corps = decode(envoi.responseText);
      if (envoi.status >= 200 && envoi.status < 300) {
        resolve((envoi.status === 204 ? undefined : corps) as T);
        return;
      }
      reject(new ApiError(envoi.status, corps.detail, corps));
    });
    // Une panne de transport n'a ni statut ni corps : la distinguer d'un refus évite
    // d'afficher « HTTP 0 » comme si le serveur avait répondu quelque chose.
    envoi.addEventListener("error", () => reject(new Error("envoi interrompu par le reseau")));
    envoi.addEventListener("abort", () => reject(new UploadAborted()));

    if (signal !== undefined) {
      // Un envoi de plusieurs minutes qu'on abandonne ne doit pas continuer d'écrire sur
      // le disque de la stack : l'abandon coupe la requête, et le point d'entrée voit son
      // appelant raccrocher.
      signal.addEventListener("abort", () => envoi.abort(), { once: true });
    }
    envoi.send(file);
  });
}

/** Le corps de la réponse, ou un objet vide : un refus peut arriver sans corps lisible. */
function decode(texte: string): Record<string, unknown> {
  try {
    return JSON.parse(texte) as Record<string, unknown>;
  } catch {
    return {};
  }
}
