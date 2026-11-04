import type { Method } from "../api/ingestion";

/**
 * Le contrat publié, restreint à UNE source et rendu CONCRET.
 *
 * Le contrat versionné décrit des gabarits — `/ingest/{source}/{mode}` —, parce qu'il
 * vaut pour tout environnement quel que soit son paramétrage. Un intégrateur, lui, reçoit
 * une adresse : `/ingest/integration-des-sites/tableau`. Cette fonction substitue les
 * adresses réelles de la source et retire les paramètres de chemin qui n'en sont plus —
 * ils sont écrits dans l'adresse.
 *
 * Rien n'est inventé : tout vient du contrat publié et des méthodes que le serveur
 * déclare. Recopier une description ou un en-tête ici en aurait fait une seconde vérité,
 * qui aurait divergé au premier changement du contrat.
 */
type Dict = Record<string, unknown>;

function dict(valeur: unknown): Dict {
  return valeur !== null && typeof valeur === "object" ? (valeur as Dict) : {};
}

/**
 * Le corps attendu, dit avec le MODÈLE de l'entrée de source quand le mode le détermine.
 *
 * Le contrat générique ne peut annoncer qu'un objet ou un tableau d'objets : il ne
 * connaît pas le modèle, qui vient du paramétrage. Ici on le connaît, et c'est ce que
 * l'intégrateur est venu chercher.
 *
 * **Le mode `fichier` garde le schéma du contrat** : son corps est un DOCUMENT dont le
 * découpage déclaré par la source désigne un tableau quelque part dedans — le modèle
 * décrit les items, pas le document. L'annoncer comme corps serait faux, et un contrat
 * faux coûte plus cher qu'un contrat vague.
 */
function corpsDeLaMethode(requestBody: Dict, method: Method): Dict {
  const contenu = dict(requestBody.content);
  const schema =
    method.mode === "element"
      ? method.request_schema
      : method.mode === "tableau"
        ? { type: "array", items: method.request_schema }
        : null;
  return {
    ...requestBody,
    content: Object.fromEntries(
      Object.entries(contenu).map(([type, media]) => {
        if (type !== "application/json") {
          return [type, media];
        }
        return [
          type,
          {
            ...dict(media),
            ...(schema === null ? {} : { schema }),
            // Le gabarit que l'essai sème dans sa zone de saisie : les deux viennent du
            // serveur, et les voir identiques des deux côtés fait partie du contrat.
            ...(method.example === null ? {} : { example: method.example }),
          },
        ];
      }),
    ),
  };
}

export function sourceSpecOf(
  spec: Record<string, unknown>,
  methods: readonly Method[],
  source: string,
): Record<string, unknown> {
  const gabarits = dict(spec.paths);
  const chemins: Dict = {};
  for (const method of methods.filter((candidate) => candidate.source === source)) {
    const post = dict(dict(gabarits[method.operation]).post);
    const parametres = Array.isArray(post.parameters) ? post.parameters : [];
    chemins[method.path] = {
      post: {
        ...post,
        // Les paramètres de CHEMIN disparaissent : l'adresse n'a plus de gabarit, et
        // Swagger demanderait une valeur pour un segment déjà écrit.
        parameters: parametres.filter((parametre) => dict(parametre).in !== "path"),
        ...(method.request_schema === null && method.example === null
          ? {}
          : { requestBody: corpsDeLaMethode(dict(post.requestBody), method) }),
      },
    };
  }
  return { ...spec, paths: chemins };
}
