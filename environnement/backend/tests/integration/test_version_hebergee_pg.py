"""La version que cette stack SERT, et ce qu'elle refuse de servir (story 3bbd4f87).

« il faut une api pour demander à l'environement de faire un pull dans la version demandé
et que le system se mette à jour » (Gael, 01/11/2026).

Ce qui est éprouvé ici n'est pas qu'un code de retour : c'est l'ARBRE posé sur le volume,
avec ses fichiers. Et surtout son contraire — qu'aucun arbre ne soit posé quand le contenu
reçu n'est pas celui que l'ordre signé désigne. C'est le seul élément authentifié de tout
l'échange, la réponse du relais n'étant pas signée.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from miles_socle.signing.calls import ORIGIN_HEADER, SIGNATURE_HEADER, sign_call
from miles_socle.signing.hosting import HOSTED_VERSION_PATH, HostedVersionIn
from miles_socle.signing.keys import load_private_key
from miles_socle.testing.enrolment_double import EXPECTED_CODE, PEER_ORIGIN, EnrolmentDouble

from environnement.hosting.model import (
    REFUSAL_BUNDLE_UNREADABLE,
    REFUSAL_RELAY_REFUSED,
    REFUSAL_WRONG_COMMIT,
    VERSION_REFUSED_EVENT,
    VERSION_SERVED_EVENT,
)
from tests.integration.bundles import VersionFabriquee, bundle_substitue, fabrique
from tests.integration.environnement_stack import EnvironnementStack, open_stack

pytestmark = pytest.mark.integration

NOM = "Recette nord"
WORKSPACE = "reseau-ferroviaire"


async def _apparie(stack: EnvironnementStack, double: EnrolmentDouble) -> None:
    ouverte = await stack.client.post(
        "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
    )
    assert ouverte.status_code == 202, ouverte.text
    conclu = await stack.client.post("/api/identity/pairing/confirm", json={"code": EXPECTED_CODE})
    assert conclu.status_code == 200, conclu.text


async def _ordonne(
    stack: EnvironnementStack,
    double: EnrolmentDouble,
    *,
    number: int,
    commit: str,
    signe: bool = True,
) -> Any:
    """L'ordre tel que l'enrôlement le pousse : signé de SA clé privée."""
    corps = (
        HostedVersionIn(workspace_id=WORKSPACE, number=number, commit=commit)
        .model_dump_json()
        .encode("utf-8")
    )
    entetes = {ORIGIN_HEADER: PEER_ORIGIN, "Content-Type": "application/json"}
    if signe:
        entetes[SIGNATURE_HEADER] = sign_call(
            load_private_key(double.keypair.private_pem),
            origin=PEER_ORIGIN,
            method="POST",
            target=HOSTED_VERSION_PATH,
            body=corps,
        )
    return await stack.anonymous().post(HOSTED_VERSION_PATH, content=corps, headers=entetes)


async def _arbre(stack: EnvironnementStack) -> list[str]:
    """Les fichiers RÉELLEMENT servis, lus du volume. La preuve, et rien d'autre."""
    vue = await stack.client.get("/api/hosting")
    assert vue.status_code == 200, vue.text
    # La route est interrogée AUSSI, et pas seulement le disque : c'est elle qui dit
    # ce que l'arbre porte, et elle doit s'accorder avec ce qu'on y lit.
    if vue.json()["tree_commit"] is None:
        return []
    return sorted(p.name for p in stack.hosting.tree.root.iterdir() if p.name != ".git")


async def _types(stack: EnvironnementStack) -> list[str]:
    rows = await stack.pool.fetch(
        "SELECT type FROM events WHERE type LIKE 'hosting.%' ORDER BY written_at"
    )
    return [row["type"] for row in rows]


def _sert(double: EnrolmentDouble, *versions: VersionFabriquee) -> None:
    for version in versions:
        double.bundles[version.commit] = version.bundle


async def test_l_ordre_signe_fait_poser_l_arbre_de_la_version(
    blank_db: str, tmp_path: Path
) -> None:
    """Le trajet complet vu de cette stack : ordre reçu, contenu tiré, arbre posé."""
    versions = fabrique(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        _sert(double, versions[1])

        recu = await _ordonne(stack, double, number=1, commit=versions[1].commit)

        assert recu.status_code == 200, recu.text
        assert recu.json()["served_commit"] == versions[1].commit
        assert recu.json()["reason"] is None
        # LA preuve : les fichiers de la version 1, sur le volume.
        assert await _arbre(stack) == ["ecran.json"]
        assert [d.commit for d in double.bundle_requests] == [versions[1].commit]
        assert await _types(stack) == [VERSION_SERVED_EVENT]


async def test_une_version_suivante_remplace_l_arbre_suppressions_comprises(
    blank_db: str, tmp_path: Path
) -> None:
    """Un fichier retiré par la nouvelle version ne doit PAS rester servi.

    Un arbre posé par recopie le laisserait en place, et la stack servirait un paramétrage
    que personne n'a publié — un incident invisible, le pire des deux.
    """
    versions = fabrique(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        _sert(double, versions[1], versions[2])
        await _ordonne(stack, double, number=1, commit=versions[1].commit)

        suivante = await _ordonne(stack, double, number=2, commit=versions[2].commit)

        assert suivante.status_code == 200, suivante.text
        assert await _arbre(stack) == ["scenario.json"]


async def test_un_bundle_qui_porte_un_autre_commit_est_refuse_sans_rien_poser(
    blank_db: str, tmp_path: Path
) -> None:
    """LE contrôle d'intégrité de tout l'échange.

    La réponse du relais n'est pas signée : seul le commit, qui voyage dans l'ordre signé,
    dit quel contenu est le bon. Ici le bundle porte BIEN l'étiquette `version/2` — il a
    l'air du bon contenu — mais elle pointe sur l'arbre de la version 1. C'est la
    substitution qu'un intermédiaire ferait, et c'est le seul cas qui exerce la
    comparaison : un bundle sans la bonne étiquette échoue dès la récupération et n'y
    arrive jamais (test suivant).
    """
    versions = fabrique(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        double.bundles[versions[2].commit] = bundle_substitue(tmp_path, 2, versions[1].commit)

        recu = await _ordonne(stack, double, number=2, commit=versions[2].commit)

        assert recu.status_code == 200, recu.text
        assert recu.json()["served_commit"] is None
        assert recu.json()["reason"] == REFUSAL_WRONG_COMMIT
        # Rien n'est posé : un arbre venu d'un contenu non vérifié servirait un
        # paramétrage que personne n'a choisi, et serait indiscernable du bon.
        assert await _arbre(stack) == []
        assert await _types(stack) == [VERSION_REFUSED_EVENT]


async def test_un_bundle_sans_l_etiquette_ordonnee_est_refuse_a_la_recuperation(
    blank_db: str, tmp_path: Path
) -> None:
    """Le cas FAIBLE, distingué du précédent parce qu'il échoue plus tôt.

    git refuse sur « couldn't find remote ref » avant toute comparaison de commit. Les
    deux refus protègent, mais ils ne passent pas par la même ligne — et confondre les
    deux ferait croire la comparaison éprouvée alors qu'elle ne le serait pas. C'est
    exactement l'erreur que la campagne du 01/11/2026 a corrigée.
    """
    versions = fabrique(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        double.bundles[versions[2].commit] = versions[1].bundle

        recu = await _ordonne(stack, double, number=2, commit=versions[2].commit)

        assert recu.json()["reason"] == REFUSAL_BUNDLE_UNREADABLE
        assert await _arbre(stack) == []


async def test_un_bundle_tronque_est_refuse_sans_rien_poser(blank_db: str, tmp_path: Path) -> None:
    versions = fabrique(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        double.bundles[versions[1].commit] = versions[1].bundle[:300]

        recu = await _ordonne(stack, double, number=1, commit=versions[1].commit)

        assert recu.json()["reason"] == REFUSAL_BUNDLE_UNREADABLE
        assert await _arbre(stack) == []


async def test_un_relais_qui_refuse_est_distingue_d_un_contenu_invalide(
    blank_db: str, tmp_path: Path
) -> None:
    """Les deux appellent un geste différent chez l'administrateur de l'enrôlement."""
    versions = fabrique(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        # Aucun bundle pour ce commit : la doublure refuse en 403, comme le vrai relais.

        recu = await _ordonne(stack, double, number=1, commit=versions[1].commit)

        assert recu.json()["reason"] == REFUSAL_RELAY_REFUSED
        assert await _arbre(stack) == []


async def test_un_ordre_non_signe_est_refuse_avant_toute_lecture(
    blank_db: str, tmp_path: Path
) -> None:
    """Sans cela, n'importe qui ferait servir à cette stack le paramétrage de son choix."""
    versions = fabrique(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        _sert(double, versions[1])

        refuse = await _ordonne(stack, double, number=1, commit=versions[1].commit, signe=False)

        assert refuse.status_code == 401, refuse.text
        assert refuse.json()["detail"] == "signature_refusee"
        assert double.bundle_requests == []
        assert await _arbre(stack) == []


async def test_un_ordre_rejoue_sur_un_arbre_conforme_ne_retire_rien(
    blank_db: str, tmp_path: Path
) -> None:
    """Rien ne s'est passé, et le journal ne doit pas dire le contraire."""
    versions = fabrique(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        _sert(double, versions[1])
        await _ordonne(stack, double, number=1, commit=versions[1].commit)

        rejoue = await _ordonne(stack, double, number=1, commit=versions[1].commit)

        assert rejoue.json()["served_commit"] == versions[1].commit
        # Le contenu n'est PAS redemandé : c'est l'arbre qui décide, et il est conforme.
        assert len(double.bundle_requests) == 1
        assert await _types(stack) == [VERSION_SERVED_EVENT]


async def test_un_ordre_rejoue_sur_un_volume_NEUF_refait_le_travail(
    blank_db: str, tmp_path: Path
) -> None:
    """Le geste de réparation, et la raison pour laquelle on interroge git et pas la table.

    Un redéploiement remplace les images sans toucher au volume ; une première
    installation ou un disque perdu laisse pourtant la table affirmer qu'on sert une
    version dont il ne reste rien. Croire la table rendrait « renvoyer l'ordre » inopérant.
    """
    versions = fabrique(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        _sert(double, versions[1])
        await _ordonne(stack, double, number=1, commit=versions[1].commit)
        shutil.rmtree(stack.hosting.tree.root)

        rejoue = await _ordonne(stack, double, number=1, commit=versions[1].commit)

        assert rejoue.json()["served_commit"] == versions[1].commit
        assert len(double.bundle_requests) == 2
        assert await _arbre(stack) == ["ecran.json"]


async def test_la_lecture_de_ce_qui_est_heberge_exige_une_session(
    blank_db: str, tmp_path: Path
) -> None:
    """Fail closed : seule la route de pair échappe à la session, et elle est signée."""
    async with open_stack(blank_db, tmp_path) as stack:
        refuse = await stack.anonymous().get("/api/hosting")

        assert refuse.status_code == 401, refuse.text
