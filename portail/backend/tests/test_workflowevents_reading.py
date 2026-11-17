"""Ce que la branche déclare, périmètre par périmètre — sans dépôt ni forge.

Ce fichier naît d'un défaut réel et de son coût. La lecture vivait dans le service, donc
elle ne s'éprouvait qu'avec un vrai dépôt, c'est-à-dire en campagne. Le 17/11/2026, un
périmètre SANS artefact a été passé à `parse`, qui refuse le texte vide (« mismatched
input '<EOF>' expecting … ») : style, types et 943 tests unitaires sont restés verts, et
c'est la campagne qui l'a dit — dix tests rouges, dont tout geste d'écriture, parce que
l'écriture passe par la même lecture.

La leçon est la même que celle de `miles.datamodels.usages` : une lecture qui ne prend
qu'un `Reader` et des chemins s'éprouve en une seconde. Celle-ci en prend un depuis.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from miles.workflowevents.dsl import FragmentError
from miles.workflowevents.reading import Perimeter, Reader, declared_in, read_perimeters

SHARED_WF = "shared/shared.wf"
ACHATS_WF = "domains/achats/achats.wf"
DEMANDE = "shared/models/demande.yaml"
COMMANDE = "domains/achats/models/commande.yaml"


def branch(files: dict[str, str], extra: Sequence[str] = ()) -> tuple[list[str], Reader]:
    """Une branche en mémoire : ses chemins, et de quoi lire ceux qui portent du texte."""
    paths = sorted({*files, *extra})

    async def read(path: str) -> str | None:
        return files.get(path)

    return paths, read


async def perimeters(files: dict[str, str], extra: Sequence[str] = ()) -> tuple[Perimeter, ...]:
    paths, read = branch(files, extra)
    return await read_perimeters(read, paths)


async def test_un_perimetre_sans_artefact_ne_declare_rien_et_n_est_pas_une_erreur() -> None:
    """LE défaut du 17/11/2026, épinglé.

    Un domaine déclaré mais sans type d'event n'a pas d'artefact — Miles retire le fichier
    avec sa dernière déclaration. Le passer au parseur fait lever, et faisait donc paraître
    illisible toute branche portant un domaine sans type.
    """
    found = await perimeters(
        {SHARED_WF: _fragment("shared", "demande_soumise", "shared.demande")}, [DEMANDE, COMMANDE]
    )

    achats = [p for p in found if p.scope == "achats"]
    assert [(p.scope, p.types, p.problems) for p in achats] == [("achats", (), ())]
    assert achats[0].path == ACHATS_WF
    # Et la branche entière reste lisible : c'est ce qui était cassé.
    assert [d.name for d in declared_in(found)] == ["demande_soumise"]


async def test_chaque_perimetre_porte_ses_types_et_son_artefact() -> None:
    # Deux périmètres aux valeurs TOUTES différentes : un seul laisserait passer une
    # lecture qui attribue tout au premier.
    found = await perimeters(
        {
            SHARED_WF: _fragment("shared", "demande_soumise", "shared.demande"),
            ACHATS_WF: _fragment("achats", "commande_validee", "domains.achats.commande"),
        },
        [DEMANDE, COMMANDE],
    )

    assert [(p.scope, p.path, [d.name for d in p.types]) for p in found] == [
        ("shared", SHARED_WF, ["demande_soumise"]),
        ("achats", ACHATS_WF, ["commande_validee"]),
    ]
    assert found[1].types[0].model_path == COMMANDE


async def test_un_artefact_illisible_n_arrete_que_son_perimetre() -> None:
    found = await perimeters(
        {
            SHARED_WF: _fragment("shared", "demande_soumise", "shared.demande"),
            ACHATS_WF: "FRAGMENT NAME achats\nDEFINE EVENT ;\n",
        },
        [DEMANDE],
    )

    rendu = {p.scope: p for p in found}
    assert [d.name for d in rendu["shared"].types] == ["demande_soumise"]
    assert rendu["achats"].types == ()
    # Les positions sont celles du MOTEUR : l'écran renvoie à la ligne fautive.
    assert [p.line for p in rendu["achats"].problems] == [2]


async def test_le_tout_ou_rien_vaut_pour_les_ecritures_et_nomme_les_manquements() -> None:
    """`declared_in` est ce par quoi passe TOUTE écriture : elle refuse en bloc.

    Sans ce refus, un geste de déclaration réécrirait l'artefact d'un périmètre dont on
    n'a pas su relire le contenu, et les types qu'il portait disparaîtraient.
    """
    found = await perimeters({ACHATS_WF: "FRAGMENT NAME achats\nDEFINE EVENT ;\n"})

    with pytest.raises(FragmentError) as refus:
        declared_in(found)

    assert [p.line for p in refus.value.problems] == [2]


async def test_un_modele_absent_est_marque_sur_la_declaration_qui_le_designe() -> None:
    # Discriminant : le modèle transverse est là, celui du domaine ne l'est pas.
    found = await perimeters(
        {
            SHARED_WF: _fragment("shared", "demande_soumise", "shared.demande"),
            ACHATS_WF: _fragment("achats", "commande_validee", "domains.achats.commande"),
        },
        [DEMANDE],
    )

    assert [(d.name, d.model_missing) for d in declared_in(found)] == [
        ("demande_soumise", False),
        ("commande_validee", True),
    ]


async def test_une_branche_sans_aucun_artefact_rend_le_seul_perimetre_transverse() -> None:
    # Le cas « rien trouvé », celui qu'on oublie : une branche neuve n'a ni domaine ni
    # artefact, et ce n'est pas une erreur.
    found = await perimeters({})

    assert [(p.scope, p.path, p.types, p.problems) for p in found] == [
        ("shared", SHARED_WF, (), ())
    ]
    assert declared_in(found) == []


def _fragment(scope: str, name: str, model: str) -> str:
    return f"FRAGMENT NAME {scope}\nDEFINE EVENT {name} 'Libellé' AS @{model};\n"
