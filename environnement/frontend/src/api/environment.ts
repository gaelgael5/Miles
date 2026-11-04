import { useQuery } from "@tanstack/react-query";
import { PEERING_KEY, request } from "@miles/socle-web";

/**
 * L'environnement du référentiel auquel le module d'enrôlement nous a rattachés.
 *
 * Le seul nom qui fasse AUTORITÉ sur cet environnement : il est posé par un humain chez
 * l'enrôlement, alors que le nom déclaré de l'appariement est ce que cette stack dit
 * d'elle-même. Les deux peuvent différer, et c'est celui-ci qui compte.
 *
 * Reste à CE produit alors que tout le reste de l'appariement est au socle : le module de
 * paramétrage ne reçoit pas de devices, et n'a donc aucun environnement à lire. C'est la
 * seule chose que ce module tient en plus d'un pair.
 *
 * `fetched_at` voyage AVEC la valeur, parce qu'une valeur venue d'un autre module ne
 * s'affiche jamais sans la date à laquelle on l'a obtenue : sans elle, un repli serait
 * indiscernable d'une lecture fraîche.
 */
export interface AssignedEnvironment {
  slug: string;
  label: string;
  fetched_at: string;
}

export interface AssignedEnvironmentView {
  environment: AssignedEnvironment | null;
  /**
   * Vrai quand la valeur vient d'être relue chez le pair. Ne se déduit PAS de
   * `environment` : « le pair est injoignable et on n'a jamais rien su » et « le pair dit
   * qu'aucun environnement ne nous est rattaché » rendent tous deux `environment: null`,
   * et les confondre annoncerait « aucun environnement » à un administrateur dont le
   * réseau est coupé.
   */
  fresh: boolean;
}

/**
 * L'environnement assigné, relu CHEZ LE PAIR à chaque affichage.
 *
 * Sa propre requête, et non un champ de l'état d'appariement : les deux émettent chacune
 * un appel signé vers le pair, et les fondre ferait échouer l'une avec l'autre. L'écran
 * veut au contraire pouvoir dire « apparié, mais l'environnement n'a pas pu être rafraîchi ».
 *
 * Rangée sous la clef de l'appariement — celle du socle — parce qu'un ré-appariement
 * change ce que cette lecture rend : les deux doivent s'invalider ensemble.
 *
 * Aucune relecture périodique : ce nom ne change que par un geste humain à l'autre bout,
 * et le serveur paie un appel sortant à chaque lecture.
 */
export function useAssignedEnvironment() {
  return useQuery({
    queryKey: [...PEERING_KEY, "environment"],
    queryFn: ({ signal }) =>
      request<AssignedEnvironmentView>("/api/identity/environment", { signal }),
  });
}
