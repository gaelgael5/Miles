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

/** Une réponse déclarée par le contrat publié : son statut et ce qu'elle signifie. */
export interface ContractResponse {
  status: string;
  description: string;
}

const INGEST_OPERATION = "/ingest/{source}/{mode}";

export function useIngestionMethods() {
  return useQuery({
    queryKey: ["ingestion", "methods"],
    queryFn: ({ signal }) =>
      request<{ methods: Method[] }>("/api/ingestion/methods", { signal }),
  });
}

/**
 * Les réponses du contrat PUBLIÉ, lues et non recopiées.
 *
 * Recopier les codes de refus dans l'écran en ferait une seconde vérité, qui divergerait
 * au premier refus ajouté. On lit donc ce que le dépôt versionné porte — c'est la même
 * fonction qui engendre le fichier.
 */
export function useIngestionContract() {
  return useQuery({
    queryKey: ["ingestion", "contract"],
    queryFn: async ({ signal }) => {
      const spec = await request<Record<string, unknown>>("/api/ingestion/contract", {
        signal,
      });
      return responsesOf(spec);
    },
  });
}

/** Les réponses de l'opération de dépôt, triées par statut croissant. */
export function responsesOf(spec: Record<string, unknown>): ContractResponse[] {
  const paths = spec.paths as Record<string, unknown> | undefined;
  const operation = (paths?.[INGEST_OPERATION] as Record<string, unknown> | undefined)?.post;
  const responses = (operation as Record<string, unknown> | undefined)?.responses;
  if (responses === undefined || responses === null || typeof responses !== "object") {
    return [];
  }
  return Object.entries(responses as Record<string, { description?: string }>)
    .map(([status, body]) => ({ status, description: body.description ?? "" }))
    .sort((left, right) => left.status.localeCompare(right.status));
}

/**
 * Essaie une méthode en déposant `body` tel quel.
 *
 * `File` autant que `string` : le mode fichier dépose un DOCUMENT choisi sur le disque
 * (critère 21 de la story 0f14adbd), et le relais est le même — la route d'écran recopie
 * le corps vers le point d'entrée. Le type de contenu annoncé dit ce qui est vraiment
 * envoyé ; la route d'essai ne s'en sert pas, elle présente celui de l'ingestion.
 */
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
