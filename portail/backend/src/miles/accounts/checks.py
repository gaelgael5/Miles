from __future__ import annotations

from typing import Any

from miles.accounts.layout import SERVED_MODES, Delivery, ReferenceProblem
from miles.datamodels.grammar import load_yaml
from miles.datamodels.layout import MODEL_RE, model_path
from miles.datamodels.navigate import kind_at
from miles.datamodels.schema import parse_schema
from miles.transform.jpath import property_keys
from miles.workshop.reading import Read

# Ce que le champ d'adresse peut désigner : une valeur, jamais un conteneur. Une adresse
# d'envoi est une chaîne ; un tableau ou un objet ne s'envoie pas, et le découvrir au
# premier terminal réel coûterait bien plus que de le refuser ici.
_CONTAINERS = {"array": "tableau_interdit", "object": "valeur_attendue"}


async def delivery_problem(
    read: Read, model: str, delivery: Delivery, where: str
) -> ReferenceProblem | None:
    """Ce que l'envoi exige du modèle du stockage : un mode servi, et un champ qui existe.

    `where` est le chemin à nommer dans le refus — le fichier à la lecture, le champ de
    saisie à l'enregistrement : la même vérification sert aux deux, et c'est ce qui
    garantit qu'un fichier écrit à la main reçoit le MÊME verdict qu'une saisie d'écran.
    """
    if delivery.mode not in SERVED_MODES:
        return ReferenceProblem(where, "mode_non_servi", delivery.mode)
    keys = property_keys(delivery.field)
    if keys is None:
        return ReferenceProblem(where, "chemin_de_propriete_attendu", delivery.field)
    match = MODEL_RE.match(model)
    if match is None:
        return ReferenceProblem(where, "modele_invalide", model)
    root = await _schema(read, match["scope"], match["name"])
    if root is None:
        return ReferenceProblem(where, "modele_illisible", model)
    kind = await kind_at(read, match["scope"], root, keys)
    if kind is None:
        return ReferenceProblem(where, "champ_inconnu", delivery.field)
    code = _CONTAINERS.get(kind)
    return None if code is None else ReferenceProblem(where, code, delivery.field)


async def _schema(read: Read, scope: str, name: str) -> Any:
    text = await read(model_path(scope, name))
    if text is None:
        return None
    try:
        parse_schema(text)
    except ValueError:
        return None
    return load_yaml(text)
