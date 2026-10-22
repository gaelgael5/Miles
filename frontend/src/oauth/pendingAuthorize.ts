/**
 * La demande d'autorisation OAuth en attente d'une connexion.
 *
 * Une connexion par annuaire OIDC revient toujours sur « / » : sans cette mémoire, la
 * personne qui n'était pas connectée perdrait la demande de claude.ai en se connectant.
 * Gardée pour l'onglet seulement (sessionStorage) ; illisible, on n'invente rien.
 */
export const AUTHORIZE_PATH = "/oauth/authorize";
const KEY = "miles.oauth.pending";

export function rememberPendingAuthorize(location: Location = window.location): void {
  if (location.pathname !== AUTHORIZE_PATH || !location.search) {
    return;
  }
  try {
    sessionStorage.setItem(KEY, location.search);
  } catch {
    // Stockage refusé (navigation privée) : la connexion par mot de passe, qui ne
    // quitte pas la page, garde la demande ; une connexion OIDC la perdra, sans plus.
  }
}

/** Ramène sur l'écran de consentement après la connexion, une seule fois. */
export function restorePendingAuthorize(): void {
  let search: string | null = null;
  try {
    search = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
  } catch {
    return;
  }
  if (search && window.location.pathname === "/") {
    window.history.replaceState(null, "", AUTHORIZE_PATH + search);
  }
}

/** Sortie vers le client OAuth : un objet pour que les tests la remplacent sans jsdom. */
export const navigation = {
  assign(url: string): void {
    window.location.assign(url);
  },
};

export function forgetPendingAuthorize(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // Rien à oublier si le stockage est refusé.
  }
}
