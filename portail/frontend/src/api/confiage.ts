import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PEERING_KEY, request } from "@miles/socle-web";

/**
 * Ce que le module d'enrôlement détient de nos connexions git, et depuis quand.
 *
 * Reste à CE produit alors que tout l'appariement est au socle : le module
 * d'environnement ne confie rien — il n'a pas de connexion git à lui, et c'est tout
 * l'objet de la décision de sécurité du ticket edcf78bc. C'est la seule chose que le
 * module de paramétrage tient en plus d'un pair.
 *
 * AUCUN credential ne figure dans cette forme, et il n'en existe pas de variante
 * tronquée : un fragment de PAT affiché est encore un secret divulgué.
 */
export interface ConfidingState {
  /** Nul quand aucun module d'enrôlement n'est apparié : il n'y a personne à qui confier. */
  peer_base_url: string | null;
  revision: number | null;
  /** Nul quand rien ne lui a encore été transmis. Différent de « transmis puis périmé ». */
  transmitted_at: string | null;
  /**
   * Vrai quand ce qu'il détient est ce que nous avons. Ne se déduit PAS de la présence
   * d'une date : il peut détenir une photo plus ancienne, et c'est précisément le cas
   * qu'il faut nommer — une transmission a échoué, et personne ne le saurait autrement.
   */
  up_to_date: boolean;
  connections: number;
}

const CONFIDING_KEY = [...PEERING_KEY, "confided"];

/**
 * Rangée sous la clef de l'appariement : un ré-appariement change ce que cette lecture
 * rend — on n'a rien transmis au nouveau pair —, donc les deux s'invalident ensemble.
 */
export function useConfidingState() {
  return useQuery({
    queryKey: CONFIDING_KEY,
    queryFn: ({ signal }) => request<ConfidingState>("/api/git-connections/confided", { signal }),
  });
}

/**
 * Retransmet l'état complet. Le geste de réparation, et le seul qui rende le refus.
 *
 * Les transmissions automatiques avalent leurs pannes — un geste d'administration ne doit
 * pas échouer parce qu'un autre module est injoignable. Celle-ci est demandée par une
 * personne : elle doit voir pourquoi ça ne passe pas.
 */
export function useTransmitConfided() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      request<ConfidingState>("/api/git-connections/confided", { method: "POST" }),
    onSettled: () => client.invalidateQueries({ queryKey: CONFIDING_KEY }),
  });
}
