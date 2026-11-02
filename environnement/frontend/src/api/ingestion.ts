import { useQuery } from "@tanstack/react-query";
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
