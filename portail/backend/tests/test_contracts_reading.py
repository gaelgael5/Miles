"""La lecture d'un contrat ne valide plus, et c'est COMPTÉ.

« On valide les documents seulement à la sauvegarde et au commit » (Gael, 18/11/2026,
enabler ee2c3665). Un gain de performance sans garde revient au premier refactor de bonne
foi : ces tests ne mesurent pas des secondes — ils comptent les confrontations, et
rougissent si l'affichage se remet à valider.

Éprouvé en UNITAIRE et non en campagne : `contract_at` prend un lecteur
(`Read = Callable[[str], Awaitable[str | None]]`), donc un dictionnaire suffit. C'est la
leçon du 17/11/2026 — une fonction qui ne fait que LIRE les fichiers d'une branche prend un
lecteur, jamais la copie de travail, et s'éprouve alors sans dépôt ni forge.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from miles.contracts import derived as derived_module
from miles.contracts import openapi as openapi_module
from miles.contracts.derived import UNDERIVABLE, UP_TO_DATE, derive_models, derived_contents
from miles.contracts.layout import meta_path, version_path
from miles.contracts.openapi import ContractInvalidError, parse_contract, read_contract
from miles.contracts.reading import contract_at

SLUG = "materiel"
# Les chemins par les fonctions qui les composent, jamais épelés : un test qui recopie un
# chemin reste vert le jour où le dépôt le déplace, et ne prouve plus rien.
META = meta_path(SLUG)
V1 = version_path(SLUG, 1)

DOCUMENT: dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Matériel", "version": "1"},
    "paths": {"/points": {"get": {"operationId": "points", "responses": {"200": {}}}}},
    "components": {
        "schemas": {"Point": {"type": "object", "properties": {"n": {"type": "string"}}}}
    },
}


class _Compteur:
    """Un validateur qui ne valide rien et dit combien de fois on l'a sollicité."""

    def __init__(self) -> None:
        self.appels = 0

    def iter_errors(self, *_instance: Any) -> list[Any]:
        # Les deux validateurs n'ont pas la même forme, et la doublure sert les deux : le
        # validateur de spécification reçoit le document à la CONSTRUCTION
        # (`validator(data).iter_errors()`), le méta-schéma le reçoit à l'ITÉRATION
        # (`_META.iter_errors(body)`). Une doublure qui n'accepterait qu'une des deux
        # formes rougirait sur sa propre signature au lieu de compter.
        self.appels += 1
        return []

    def __call__(self, _schema: Any) -> _Compteur:
        # `parse_contract` INSTANCIE le validateur de la version rencontrée : la doublure
        # se rend donc elle-même, pour compter l'instanciation et l'itération au même
        # endroit.
        return self


@pytest.fixture
def compteurs(monkeypatch: pytest.MonkeyPatch) -> tuple[_Compteur, _Compteur]:
    """Les deux confrontations de la route : la spécification, et le méta-schéma."""
    specification, meta = _Compteur(), _Compteur()
    monkeypatch.setattr(openapi_module, "SUPPORTED", {"3.0": specification, "3.1": specification})
    monkeypatch.setattr(derived_module, "_META", meta)
    return specification, meta


def _lecteur(fichiers: dict[str, str]):
    async def read(path: str) -> str | None:
        return fichiers.get(path)

    return read


def _branche(document: dict[str, Any] | None = None) -> dict[str, str]:
    """Une branche portant le contrat, sa version, et le modèle dérivé que git a."""
    doc = DOCUMENT if document is None else document
    fichiers = {
        META: yaml.safe_dump({"slug": SLUG, "label": "Matériel", "sens": "externe"}),
        V1: yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
    }
    for model in derived_contents(doc, SLUG, 1):
        fichiers[model.path] = model.content
    return fichiers


async def test_lire_un_contrat_ne_confronte_ni_la_specification_ni_le_meta_schema(
    compteurs: tuple[_Compteur, _Compteur],
) -> None:
    """La garde du gain : ZÉRO confrontation pour un affichage."""
    specification, meta = compteurs
    fichiers = _branche()

    contract = await contract_at(_lecteur(fichiers), list(fichiers), SLUG)

    assert specification.appels == 0
    assert meta.appels == 0
    # Et l'écran a tout ce qu'il montre : le titre, les opérations, l'état des modèles.
    assert contract is not None
    version = contract.versions[0]
    assert version.parsed is not None
    assert (version.parsed.title, version.parsed.openapi) == ("Matériel", "3.1.0")
    assert [(o.method, o.path) for o in version.parsed.operations] == [("get", "/points")]
    assert version.models is not None and version.models.state == UP_TO_DATE


def test_sauvegarder_confronte_encore_les_deux(compteurs: tuple[_Compteur, _Compteur]) -> None:
    """L'autre moitié de la garde, sans laquelle « zéro » serait vrai partout.

    Un test qui n'affirmerait que le zéro de la lecture resterait vert si la validation
    disparaissait du dépôt entier : c'est exactement la panne que cette décision ne veut
    pas introduire.
    """
    specification, meta = compteurs

    parse_contract(yaml.safe_dump(DOCUMENT))
    assert specification.appels == 1

    derive_models(DOCUMENT, SLUG, 1)
    assert meta.appels == 1


async def test_un_modele_derive_invalide_se_lit_a_rederiver_et_non_non_derivable() -> None:
    """La conséquence ASSUMÉE de la décision, écrite comme telle.

    `exclusiveMinimum` sans type numérique produit un modèle que le méta-schéma 2020-12
    refuse. À l'écriture et au figement, `derive_models` le dit « non dérivable » ; à
    l'affichage, le modèle est produit et comparé, donc l'écran dit « à redériver ». Sans
    ce test, l'écart se découvrirait comme un bug plutôt que comme un arbitrage.
    """
    document = DOCUMENT | {
        "components": {"schemas": {"Point": {"type": "object", "exclusiveMinimum": "non"}}}
    }
    # Le fichier est là, mais git ne porte aucun modèle dérivé : l'état sera « à
    # redériver » parce que les noms ne correspondent pas, pas parce qu'on a validé.
    fichiers = {
        META: yaml.safe_dump({"slug": SLUG, "label": "Matériel", "sens": "externe"}),
        V1: yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
    }

    contract = await contract_at(_lecteur(fichiers), list(fichiers), SLUG)

    assert contract is not None
    assert contract.versions[0].models is not None
    assert contract.versions[0].models.state != UNDERIVABLE


def test_lire_refuse_toujours_une_reference_externe_et_une_version_non_prise_en_charge() -> None:
    """Les gardes qui RESTENT sur le chemin de lecture, et pourquoi elles y restent.

    La `$ref` externe est une garde de sécurité — un document chargé sans elle serait prêt
    à faire sortir une requête du serveur dès qu'un appelant le validerait — et elle coûte
    4 ms. Sans elle sur ce chemin, l'allègement de l'affichage aurait ouvert une porte.
    """
    externe = DOCUMENT | {
        "components": {"schemas": {"Point": {"$ref": "https://exemple.fr/p.json"}}}
    }

    with pytest.raises(ContractInvalidError):
        read_contract(yaml.safe_dump(externe))

    with pytest.raises(ContractInvalidError):
        # Sans la validation de spécification, c'est la lecture qui doit refuser un
        # document sans `info.title` — sinon elle lèverait un KeyError, et la route
        # rendrait 500 au lieu de nommer le manquement.
        read_contract(yaml.safe_dump({"openapi": "3.1.0", "paths": {}}))
