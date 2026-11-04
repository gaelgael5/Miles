"""Comment une clé est PRÉSENTÉE dans un appel, et quand on refuse de choisir.

Extrait au socle le 02/11/2026, deuxième usage : la surface MCP du portail et le point
d'entrée d'ingestion d'un environnement lisent la même chose. La règle n'est pas « comment
lire un en-tête » — chaque cadre le fait à sa façon — mais **ce qu'on retient de ce qui a
été présenté**, et c'est cela qui ne doit pas diverger.
"""

from __future__ import annotations

BEARER = "bearer"
# Le nom de l'en-tête dédié. Une constante plutôt qu'un littéral répété : depuis le
# 04/11/2026 il y a un ÉCRIVAIN en plus des lecteurs — le back-office d'un environnement
# frappe sa propre route d'ingestion avec sa clé —, et deux littéraux auraient divergé au
# premier renommage, sans que rien ne paraisse faux de part ni d'autre.
API_KEY_HEADER = "X-API-Key"


def key_from_headers(authorization: str | None, api_key: str | None) -> str | None:
    """La clé présentée, ou None si rien d'exploitable ne l'a été.

    **Deux en-têtes portant deux valeurs différentes : aucune n'est retenue.** Choisir
    l'une reviendrait à laisser l'appelant décider laquelle on vérifie — et donc à lui
    laisser présenter une clé valide à côté d'une autre pour voir laquelle passe.

    Un `Authorization` d'un autre schéma que `Bearer` **refuse tout**, même si un
    `X-API-Key` valable l'accompagne : un appel qui s'authentifie de deux façons dont
    l'une est incomprise n'est pas un appel dont on devine l'intention.
    """
    trouvees: set[str] = set()
    presentee = (authorization or "").strip()
    if presentee:
        schema, _, valeur = presentee.partition(" ")
        if schema.lower() != BEARER or not valeur.strip():
            return None
        trouvees.add(valeur.strip())
    directe = (api_key or "").strip()
    if directe:
        trouvees.add(directe)
    return trouvees.pop() if len(trouvees) == 1 else None
