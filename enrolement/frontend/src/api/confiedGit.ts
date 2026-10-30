import { useQuery } from "@tanstack/react-query";
import { request } from "@miles/socle-web";

/**
 * Les connexions git que le module de paramétrage a confiées à ce module.
 *
 * Ce module les DÉTIENT pour le compte des environnements : un module d'environnement n'en
 * reçoit jamais le credential, il lira git par le relais (ticket edcf78bc). Deux propriétés
 * en découlent, et c'est pour elles que la chaîne existe plutôt qu'une distribution : un
 * environnement compromis ne livre pas l'accès au dépôt, et un environnement révoqué perd
 * son accès à git sans qu'on révoque quoi que ce soit chez la forge.
 *
 * AUCUN champ ne porte le credential, et il n'en existe pas de variante tronquée.
 */
export interface ConfidedWorkspace {
  id: string;
  /** Nul pour un workspace dont le dépôt n'est pas encore configuré chez le paramétrage. */
  repo_url: string | null;
}

export interface ConfidedConnection {
  id: string;
  label: string;
  base_url: string;
  confided_at: string;
  /** Nul tant que le credential n'a jamais été remplacé, et c'est l'état normal. */
  renewed_at: string | null;
  workspaces: ConfidedWorkspace[];
}

export interface ConfidedGitState {
  /**
   * Nul quand AUCUN module de paramétrage n'est apparié. Distinct d'une liste vide :
   * « personne ne nous confie rien » et « apparié, mais rien de confié » n'appellent pas
   * le même geste, et confondre les deux ferait chercher une panne de forge.
   */
  peer_base_url: string | null;
  revision: number | null;
  received_at: string | null;
  connections: ConfidedConnection[];
}

export interface ConfidedConnectionDetail {
  connection: ConfidedConnection;
  /**
   * Faux quand le chiffré ne s'ouvre plus ici — MILES_SECRETS_KEY changée, ligne altérée.
   * C'est le cas qu'il faut distinguer d'une panne de forge : le geste à faire est de le
   * faire reconfier depuis le module de paramétrage, pas de chercher du côté du dépôt.
   */
  credential_readable: boolean;
}

export const CONFIDED_GIT_KEY = ["confided-git"];

export function useConfidedGitConnections() {
  return useQuery({
    queryKey: CONFIDED_GIT_KEY,
    queryFn: ({ signal }) =>
      request<ConfidedGitState>("/api/pairing/git-connections", { signal }),
  });
}

/**
 * Le détail d'une connexion, demandé seulement quand un humain le réclame.
 *
 * `enabled` plutôt qu'un appel systématique : la lecture OUVRE le chiffré pour savoir
 * s'il s'ouvre, et le faire pour chaque ligne à chaque affichage dépenserait du
 * déchiffrement pour une information que personne ne regarde.
 */
export function useConfidedGitConnection(connectionId: string, enabled: boolean) {
  return useQuery({
    queryKey: [...CONFIDED_GIT_KEY, connectionId],
    enabled,
    queryFn: ({ signal }) =>
      request<ConfidedConnectionDetail>(`/api/pairing/git-connections/${connectionId}`, {
        signal,
      }),
  });
}
