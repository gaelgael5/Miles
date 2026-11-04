/** Erreur HTTP de l'API, avec le `detail` qu'elle renvoie pour que l'écran dise pourquoi. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
    /**
     * Le corps ENTIER du refus, pour les rares réponses qui portent plus que leur code.
     *
     * Ajouté le 28/10/2026 : le refus d'un code d'appariement pour dérive d'horloge
     * annonce de combien elle dérive, et un écran qui ne peut pas le lire doit inventer
     * un nombre ou taire la seule information utile. `detail` reste le chemin ordinaire.
     */
    readonly payload: Record<string, unknown> = {},
  ) {
    super(`HTTP ${status}`);
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
    throw new ApiError(response.status, body.detail, body);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

/** Champ nommé par une réponse 422 `{detail: {field}}`, ou null. */
export function invalidField(error: unknown): string | null {
  if (error instanceof ApiError && error.status === 422) {
    const detail = error.detail as { field?: unknown } | undefined;
    return typeof detail?.field === "string" ? detail.field : null;
  }
  return null;
}
