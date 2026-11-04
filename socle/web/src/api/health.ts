import { useQuery } from "@tanstack/react-query";

export interface HealthResponse {
  status: "ok" | "degraded";
  database: "up" | "down";
  schema_version: number | null;
  expected_schema_version: number;
}

export class BackendUnreachableError extends Error {}

const HEALTH_REFRESH_MS = 30_000;

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch("/api/health", { signal });
  // 503 porte un corps exploitable (base ou schéma en défaut) : on le lit au lieu
  // de le traiter comme une panne réseau, sinon l'écran ne dirait pas laquelle.
  if (response.status !== 200 && response.status !== 503) {
    throw new BackendUnreachableError(`HTTP ${response.status}`);
  }
  return (await response.json()) as HealthResponse;
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => fetchHealth(signal),
    refetchInterval: HEALTH_REFRESH_MS,
  });
}
