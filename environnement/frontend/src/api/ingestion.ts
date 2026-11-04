import { useMutation, useQuery } from "@tanstack/react-query";
import { request } from "@miles/socle-web";

/**
 * L'état du service d'ingestion et le journal de ses appels.
 *
 * Lecture seule : ce que la stack expose en entrée vient du paramétrage versionné, et
 * une route qui le changerait ici créerait une seconde vérité sur ce qu'elle reçoit.
 */
export interface Endpoint {
  source: string;
  storage: string;
  entry_model: string;
  mode: string;
  /** L'adresse complète à appeler : c'est elle qu'on donne au partenaire. */
  path: string;
  /** Faux pour un mode que le paramétrage déclare et que la stack ne sert pas encore. */
  served: boolean;
}

export interface Health {
  /** Nuls sans version servie : aucune source n'est alors déclarée, donc aucune entrée. */
  version_number: number | null;
  version_commit: string | null;
  version_served_at: string | null;
  endpoints: Endpoint[];
  unreadable_sources: string[];
  active_keys: number;
  never_used_keys: number;
  deposits_total: number;
  deposits_recent: number;
  last_deposit_at: string | null;
  /** Les modes de masse pas encore servis : il n'y a aucune file à surveiller. */
  bulk_modes: string[];
}

export interface Call {
  id: string;
  source: string;
  mode: string;
  entry_model: string;
  object_count: number;
  size_bytes: number;
  version_number: number;
  key_label: string;
  /** Le préfixe affiché, jamais la valeur. Nul si la clé n'est plus en base. */
  key_prefix: string | null;
  received_at: string;
  state: string;
}

export interface CallPage {
  calls: Call[];
  total: number;
  page: number;
  page_size: number;
  sources: string[];
}

export function useIngestionHealth() {
  return useQuery({
    queryKey: ["ingestion", "health"],
    queryFn: ({ signal }) => request<Health>("/api/ingestion/health", { signal }),
  });
}

export function useIngestionCalls(source: string, page: number) {
  const params = new URLSearchParams({ page: String(page) });
  if (source !== "") {
    params.set("source", source);
  }
  return useQuery({
    queryKey: ["ingestion", "calls", source, page],
    queryFn: ({ signal }) => request<CallPage>(`/api/ingestion/calls?${params}`, { signal }),
  });
}

/**
 * Ce que chaque méthode d'ingestion ATTEND, pour que l'écran se lise comme un contrat.
 *
 * `request_schema` est le modèle d'entrée que l'entrée de source déclare, renvois
 * résolus. Nul quand la version servie ne le porte pas — et `model_refusal` dit alors
 * lequel manque, plutôt qu'un corps vide qui se lirait comme « cette méthode n'attend
 * rien ».
 */
export interface Method {
  source: string;
  storage: string;
  entry_model: string;
  mode: string;
  path: string;
  /** Faux pour un mode déclaré que la stack ne sert pas encore : montré, sans bouton. */
  served: boolean;
  request_schema: unknown | null;
  model_refusal: string | null;
  example: unknown | null;
  /**
   * Le gabarit sous lequel le contrat publie cette méthode.
   *
   * C'est la clé par laquelle la page retrouve sa SIGNATURE. Donnée par le serveur et non
   * déduite de `path` : la déduction aurait rompu au premier chemin littéral ajouté — le
   * mode fichier en est un —, et la page aurait cherché une opération qui n'existe pas.
   */
  operation: string;
}

/**
 * Ce que le point d'entrée a répondu à un essai, rendu tel quel.
 *
 * `status` est celui du DÉPÔT, pas celui de la route d'écran : un lot entièrement rejeté
 * rend 422 au partenaire, et la page doit le montrer comme tel plutôt que comme une
 * panne. La route d'écran répond donc 200 en portant ce 422.
 */
export interface Trial {
  status: number;
  body: unknown;
}

/** Une réponse déclarée par le contrat publié : son statut, ce qu'elle signifie, sa forme. */
export interface ContractResponse {
  status: string;
  description: string;
  /** Le schéma du corps rendu, renvois résolus. Nul pour une réponse sans corps. */
  schema: unknown | null;
}

/** Un en-tête ou un paramètre que l'opération déclare. */
export interface ContractParameter {
  name: string;
  in: string;
  required: boolean;
  description: string;
}

/** Une façon de s'authentifier, telle que le contrat la déclare. */
export interface ContractSecurity {
  name: string;
  /** « apiKey » ou « http » : ce qui dit OÙ la clé se présente. */
  type: string;
  /** Le nom de l'en-tête pour une clé d'API ; vide pour un porteur. */
  header: string;
  description: string;
}

/**
 * La SIGNATURE d'une méthode, lue du contrat publié.
 *
 * Lue et non recopiée dans l'écran : un en-tête ajouté, un corps changé, un refus de plus
 * apparaissent ici sans qu'on touche à la page. Recopier en aurait fait une seconde
 * vérité, qui aurait divergé au premier changement — et c'est précisément ce qu'un
 * intégrateur ne peut pas vérifier depuis l'extérieur.
 */
export interface Signature {
  summary: string;
  description: string;
  parameters: ContractParameter[];
  /** Les types de contenu acceptés, et le schéma du corps pour chacun. */
  body: { contentType: string; schema: unknown }[];
  bodyDescription: string;
  bodyRequired: boolean;
  responses: ContractResponse[];
}

/** Le contrat publié, tel que la page de service le lit. */
export interface Contract {
  /** Ce que le contrat dit de lui-même : authentification, idempotence, modes, garanties. */
  description: string;
  version: string;
  security: ContractSecurity[];
  /** Les signatures, par gabarit d'opération — la clé que porte chaque méthode. */
  operations: Record<string, Signature>;
  /** La spec entière, pour qui veut engendrer un client. */
  spec: Record<string, unknown>;
}

export function useIngestionMethods() {
  return useQuery({
    queryKey: ["ingestion", "methods"],
    queryFn: ({ signal }) => request<{ methods: Method[] }>("/api/ingestion/methods", { signal }),
  });
}

export function useIngestionContract() {
  return useQuery({
    queryKey: ["ingestion", "contract"],
    queryFn: async ({ signal }) => {
      const spec = await request<Record<string, unknown>>("/api/ingestion/contract", {
        signal,
      });
      return contractOf(spec);
    },
  });
}

type Dict = Record<string, unknown>;

function dict(value: unknown): Dict {
  return value !== null && typeof value === "object" ? (value as Dict) : {};
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/**
 * Le renvoi `$ref` résolu contre les composants du contrat.
 *
 * Résolu ICI et non laissé à l'affichage : une page qui montrerait
 * `#/components/schemas/AcknowledgementOut` n'aurait rien dit de la forme rendue, et
 * l'intégrateur devrait ouvrir le fichier à côté — ce que la page existe pour éviter.
 * Un seul niveau de renvoi est suivi : au-delà, ce sont les schémas imbriqués que le
 * lecteur déplie, et les suivre tous ici recopierait le contrat entier dans chaque forme.
 */
function resolved(value: unknown, spec: Dict): unknown {
  const renvoi = text(dict(value).$ref);
  if (renvoi === "") {
    return value;
  }
  const nom = renvoi.split("/").pop() ?? "";
  const schemas = dict(dict(spec.components).schemas);
  return schemas[nom] ?? value;
}

/** La signature d'une opération : ses en-têtes, son corps, ses réponses. */
export function signatureOf(operation: Dict, spec: Dict): Signature {
  const corps = dict(dict(operation.requestBody).content);
  const reponses = dict(operation.responses);
  return {
    summary: text(operation.summary),
    description: text(operation.description),
    parameters: (Array.isArray(operation.parameters) ? operation.parameters : [])
      .map((brut) => dict(brut))
      .filter((parametre) => parametre.in !== "path")
      .map((parametre) => ({
        name: text(parametre.name),
        in: text(parametre.in),
        required: parametre.required === true,
        description: text(parametre.description),
      })),
    body: Object.entries(corps).map(([contentType, media]) => ({
      contentType,
      schema: resolved(dict(media).schema, spec),
    })),
    bodyDescription: text(dict(operation.requestBody).description),
    bodyRequired: dict(operation.requestBody).required === true,
    responses: Object.entries(reponses)
      .map(([status, brut]) => {
        const media = dict(dict(dict(brut).content)["application/json"]);
        return {
          status,
          description: text(dict(brut).description),
          schema: media.schema === undefined ? null : resolved(media.schema, spec),
        };
      })
      .sort((gauche, droite) => gauche.status.localeCompare(droite.status)),
  };
}

/** Le contrat publié, lu : sa description, ses authentifications, ses signatures. */
export function contractOf(spec: Record<string, unknown>): Contract {
  const chemins = dict(spec.paths);
  const schemes = dict(dict(spec.components).securitySchemes);
  return {
    description: text(dict(spec.info).description),
    version: text(dict(spec.info).version),
    security: Object.entries(schemes).map(([name, brut]) => ({
      name,
      type: text(dict(brut).type),
      header: text(dict(brut).name),
      description: text(dict(brut).description),
    })),
    operations: Object.fromEntries(
      Object.entries(chemins).map(([chemin, item]) => [
        chemin,
        signatureOf(dict(dict(item).post), spec),
      ]),
    ),
    spec,
  };
}

export function useTryMethod() {
  return useMutation({
    mutationFn: ({
      source,
      mode,
      body,
    }: {
      source: string;
      mode: string;
      body: string | File;
    }) =>
      request<Trial>(
        `/api/ingestion/try/${encodeURIComponent(source)}/${encodeURIComponent(mode)}`,
        {
          method: "POST",
          body,
          headers:
            typeof body === "string" ? {} : { "Content-Type": "application/octet-stream" },
        },
      ),
  });
}

/**
 * Réémet la clé du back-office, après une révocation. Rien n'est rendu de la clé : sa
 * valeur reste au serveur.
 */
export function useReissueSelfKey() {
  return useMutation({
    mutationFn: () => request<undefined>("/api/ingestion/self-key", { method: "POST" }),
  });
}
