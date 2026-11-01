"""La version du workspace qu'un environnement sert (Gael, 01/11/2026, story 3bbd4f87).

Cette campagne monte le trajet COMPLET et rien de moins : un module de paramétrage apparié
qui confie une connexion git, un vrai dépôt servi en HTTP, un environnement apparié dont la
contrepartie revient chercher le bundle et l'applique avec un vrai git. C'est le seul
montage qui éprouve ce qui compte ici — le relais, son autorisation, et le fait que le
contenu traverse. Écrire les lignes à la main ou répondre « servi » sans aller chercher
laisserait précisément ces trois choses non vérifiées.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from miles_socle.signing.hosting import HOSTING_BUNDLE_PATH, HostingBundleIn

from enrolement.hosting.model import (
    REFUSAL_NOT_APPLIED,
    VERSION_ORDERED_EVENT,
    VERSION_REFUSED_EVENT,
    VERSION_RELEASED_EVENT,
    VERSION_SERVED_EVENT,
)
from tests.integration.bundle_recu import arbre_servi
from tests.integration.demandeur_double import RequesterDouble, confide_body, connexion
from tests.integration.depot_jetable import depot_jetable
from tests.integration.enrolement_stack import (
    EnrolementStack,
    conclut_appariement,
    demande_appariement,
    open_stack,
)

pytestmark = pytest.mark.integration

CREDENTIAL = "pat-de-test-hebergement-ne-doit-jamais-sortir"
WORKSPACE = "reseau-ferroviaire"
VERSIONS = {1: "Première mise en service", 2: "Réseau ferroviaire"}


async def _parametrage(stack: EnrolementStack, repo_url: str | None) -> RequesterDouble:
    """Un paramétrage apparié qui confie une connexion exposant WORKSPACE sur `repo_url`."""
    double = RequesterDouble(origin="http://parametrage.test", species="parametrage")
    await demande_appariement(stack, double)
    await conclut_appariement(stack, double)
    charge = confide_body(1, [connexion("forge", CREDENTIAL, workspaces=[(WORKSPACE, repo_url)])])
    confie = await double.confide(stack.anonymous(), charge)
    assert confie.status_code == 200, confie.text
    return double


async def _environnement_apparie(
    stack: EnrolementStack, *, applique: bool, hosts: Path | None = None
) -> tuple[str, RequesterDouble]:
    """Un environnement du référentiel, apparié à une contrepartie, workspace placé.

    `applique=False` monte une contrepartie qui ACCUSE l'ordre sans aller chercher le
    contenu : « reçu » et « servi » sont deux faits distincts, et c'est l'un des cas que
    cette campagne doit couvrir pour lui-même.
    """
    cree = await stack.client.post(
        "/api/environments", json={"label": "Recette nord", "slug": "recette-nord"}
    )
    assert cree.status_code == 201, cree.text
    environnement = str(cree.json()["id"])
    double = RequesterDouble(origin="http://environnement.test", species="environnement")
    demande = await demande_appariement(stack, double)
    assert demande["base_url"] == double.origin
    designe = await stack.client.put(
        "/api/pairing/requests/environment",
        params={"base_url": double.origin},
        json={"environment_id": environnement},
    )
    assert designe.status_code == 200, designe.text
    await conclut_appariement(stack, double)
    if applique:
        double.back = stack.anonymous()
        double.hosts = hosts
    place = await _place(stack, environnement, WORKSPACE)
    assert place.status_code == 200, place.text
    return environnement, double


async def _place(stack: EnrolementStack, environment_id: str, workspace_id: str | None) -> Any:
    return await stack.client.put(
        f"/api/environments/{environment_id}/workspace", json={"workspace_id": workspace_id}
    )


async def _types(stack: EnrolementStack) -> list[str]:
    rows = await stack.pool.fetch(
        "SELECT type FROM events WHERE type LIKE 'environment.version%' ORDER BY written_at"
    )
    return [row["type"] for row in rows]


async def test_la_version_choisie_traverse_jusqu_a_l_arbre_que_l_environnement_sert(
    blank_db: str, tmp_path: Path
) -> None:
    """Le trajet complet, et la preuve est le CONTENU posé — pas un code de retour.

    Des commits égaux pourraient venir d'un bundle vide : c'est le fichier, avec sa
    valeur, qui prouve que le paramétrage a traversé le relais.
    """
    with depot_jetable(tmp_path, VERSIONS) as depot:
        async with open_stack(blank_db, tmp_path, git_test_hosts=(depot.host,)) as stack:
            await _parametrage(stack, depot.url)
            heberge = tmp_path / "heberge"
            environnement, double = await _environnement_apparie(
                stack, applique=True, hosts=heberge
            )

            ordonne = await stack.client.put(
                f"/api/environments/{environnement}/version", json={"number": 2}
            )

            assert ordonne.status_code == 200, ordonne.text
            attendu = depot.commits_des_versions()[2]
            assert ordonne.json()["commit"] == attendu
            assert ordonne.json()["served_commit"] == attendu
            assert ordonne.json()["up_to_date"] is True
            assert [o.number for o in double.ordered] == [2]
            # LA preuve : le contenu de la version 2, posé chez la contrepartie.
            assert arbre_servi(heberge) == "version 2\n"
            assert await _types(stack) == [VERSION_ORDERED_EVENT, VERSION_SERVED_EVENT]


async def test_les_versions_du_depot_se_lisent_depuis_le_module_d_enrolement(
    blank_db: str, tmp_path: Path
) -> None:
    """Lues dans git avec le credential confié : aucune route de pair ne les demande."""
    with depot_jetable(tmp_path, VERSIONS) as depot:
        async with open_stack(blank_db, tmp_path, git_test_hosts=(depot.host,)) as stack:
            await _parametrage(stack, depot.url)
            environnement, _ = await _environnement_apparie(stack, applique=False)

            lues = await stack.client.get(f"/api/environments/{environnement}/versions")

            assert lues.status_code == 200, lues.text
            # De la plus récente à la plus ancienne, avec son libellé et son auteur.
            assert [v["number"] for v in lues.json()] == [2, 1]
            assert lues.json()[0]["label"] == "Réseau ferroviaire"
            assert lues.json()[0]["author"] == "Alice <alice@annuaire.invalid>"
            assert lues.json()[0]["commit"] == depot.commits_des_versions()[2]


async def test_un_ordre_recu_sans_etre_applique_n_est_pas_dit_a_jour(
    blank_db: str, tmp_path: Path
) -> None:
    """« Reçu » et « servi » sont deux faits : les confondre afficherait à jour pour rien."""
    with depot_jetable(tmp_path, VERSIONS) as depot:
        async with open_stack(blank_db, tmp_path, git_test_hosts=(depot.host,)) as stack:
            await _parametrage(stack, depot.url)
            environnement, double = await _environnement_apparie(stack, applique=False)

            ordonne = await stack.client.put(
                f"/api/environments/{environnement}/version", json={"number": 1}
            )

            # 200 et non une erreur : le choix est NOTRE état, et il est enregistré. Rendre
            # une erreur ferait rechoisir la même version indéfiniment.
            assert ordonne.status_code == 200, ordonne.text
            assert ordonne.json()["served_commit"] is None
            assert ordonne.json()["refusal"] == REFUSAL_NOT_APPLIED
            assert ordonne.json()["up_to_date"] is False
            assert [o.number for o in double.ordered] == [1]
            assert await _types(stack) == [VERSION_ORDERED_EVENT, VERSION_REFUSED_EVENT]


async def test_l_ordre_se_renvoie_a_un_environnement_qui_a_tout_perdu(
    blank_db: str, tmp_path: Path
) -> None:
    """Le geste de réparation : un environnement au volume neuf ne sait rien de son ordre."""
    with depot_jetable(tmp_path, VERSIONS) as depot:
        async with open_stack(blank_db, tmp_path, git_test_hosts=(depot.host,)) as stack:
            await _parametrage(stack, depot.url)
            heberge = tmp_path / "heberge"
            environnement, double = await _environnement_apparie(
                stack, applique=True, hosts=heberge
            )
            await stack.client.put(f"/api/environments/{environnement}/version", json={"number": 2})

            renvoye = await stack.client.post(f"/api/environments/{environnement}/version/resend")

            assert renvoye.status_code == 200, renvoye.text
            assert renvoye.json()["up_to_date"] is True
            # Reçu DEUX fois, le même : renvoyer ne change pas l'ordre enregistré.
            assert [o.number for o in double.ordered] == [2, 2]
            assert [o.commit for o in double.ordered] == [renvoye.json()["commit"]] * 2


async def _demande_bundle(
    stack: EnrolementStack, double: RequesterDouble, workspace_id: str, commit: str
) -> Any:
    corps = HostingBundleIn(workspace_id=workspace_id, commit=commit).model_dump_json()
    return await double.post(stack.anonymous(), HOSTING_BUNDLE_PATH, corps.encode("utf-8"))


async def test_le_relais_sert_le_contenu_ordonne_et_rien_d_autre(
    blank_db: str, tmp_path: Path
) -> None:
    """Être apparié donne droit à SON workspace, au commit ordonné. Fail closed.

    Les trois refus rendent le MÊME code, sans détail : dire laquelle des conditions pèche
    apprendrait à une machine l'état de notre référentiel — quels workspaces existent,
    lesquels sont placés ailleurs.
    """
    with depot_jetable(tmp_path, VERSIONS) as depot:
        async with open_stack(blank_db, tmp_path, git_test_hosts=(depot.host,)) as stack:
            await _parametrage(stack, depot.url)
            environnement, double = await _environnement_apparie(stack, applique=False)
            commits = depot.commits_des_versions()
            await stack.client.put(f"/api/environments/{environnement}/version", json={"number": 2})

            ordonne = await _demande_bundle(stack, double, WORKSPACE, commits[2])
            autre_workspace = await _demande_bundle(stack, double, "caisse", commits[2])
            autre_commit = await _demande_bundle(stack, double, WORKSPACE, commits[1])

            assert ordonne.status_code == 200, ordonne.text
            # Un bundle git commence par cette signature : la réponse n'est pas du JSON,
            # et le vérifier ici prouve que les octets ont traversé sans être décodés.
            assert ordonne.content.startswith(b"# v2 git bundle")
            assert autre_workspace.status_code == 403, autre_workspace.text
            assert autre_workspace.json()["detail"] == "contenu_non_ordonne"
            assert autre_commit.status_code == 403, autre_commit.text
            assert autre_commit.json()["detail"] == "contenu_non_ordonne"


async def test_le_relais_refuse_une_demande_non_signee(blank_db: str, tmp_path: Path) -> None:
    """La signature AVANT toute lecture du corps : c'est le point d'application du fail closed."""
    with depot_jetable(tmp_path, VERSIONS) as depot:
        async with open_stack(blank_db, tmp_path, git_test_hosts=(depot.host,)) as stack:
            await _parametrage(stack, depot.url)
            environnement, _ = await _environnement_apparie(stack, applique=False)
            await stack.client.put(f"/api/environments/{environnement}/version", json={"number": 2})
            corps = HostingBundleIn(
                workspace_id=WORKSPACE, commit=depot.commits_des_versions()[2]
            ).model_dump_json()

            nue = await stack.anonymous().post(HOSTING_BUNDLE_PATH, content=corps)

            assert nue.status_code == 401, nue.text
            assert nue.json()["detail"] == "signature_refusee"


async def test_le_relais_refuse_un_pair_a_qui_rien_n_est_ordonne(
    blank_db: str, tmp_path: Path
) -> None:
    """Apparié, workspace placé, mais aucune version choisie : il n'y a rien à servir."""
    with depot_jetable(tmp_path, VERSIONS) as depot:
        async with open_stack(blank_db, tmp_path, git_test_hosts=(depot.host,)) as stack:
            await _parametrage(stack, depot.url)
            _, double = await _environnement_apparie(stack, applique=False)

            refuse = await _demande_bundle(
                stack, double, WORKSPACE, depot.commits_des_versions()[2]
            )

            assert refuse.status_code == 403, refuse.text


async def test_sans_workspace_place_il_n_y_a_pas_de_version_a_choisir(
    blank_db: str, tmp_path: Path
) -> None:
    """Le geste à faire est ailleurs — placer un workspace — et aucun message sur les
    versions ne le ferait deviner."""
    with depot_jetable(tmp_path, VERSIONS) as depot:
        async with open_stack(blank_db, tmp_path, git_test_hosts=(depot.host,)) as stack:
            await _parametrage(stack, depot.url)
            environnement, _ = await _environnement_apparie(stack, applique=False)
            await _place(stack, environnement, None)

            lues = await stack.client.get(f"/api/environments/{environnement}/versions")

            assert lues.status_code == 409, lues.text
            assert lues.json()["detail"] == "aucun_workspace_place"


async def test_un_depot_non_configure_chez_le_parametrage_se_dit(
    blank_db: str, tmp_path: Path
) -> None:
    """Un workspace déclaré avant son dépôt est un état NORMAL là-bas.

    Une liste vide affirmerait qu'il n'a aucune version publiée, ce que personne ici ne sait.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        await _parametrage(stack, None)
        environnement, _ = await _environnement_apparie(stack, applique=False)

        lues = await stack.client.get(f"/api/environments/{environnement}/versions")

        assert lues.status_code == 409, lues.text
        assert lues.json()["detail"] == "depot_non_configure"


async def test_un_parametrage_revoque_laisse_le_placement_sans_source_git(
    blank_db: str, tmp_path: Path
) -> None:
    """Le placement survit volontairement à la révocation ; la source git, non.

    Refus distinct des autres : le geste est de réapparier le paramétrage, pas de toucher
    à l'environnement ni au dépôt.
    """
    with depot_jetable(tmp_path, VERSIONS) as depot:
        async with open_stack(blank_db, tmp_path, git_test_hosts=(depot.host,)) as stack:
            parametrage = await _parametrage(stack, depot.url)
            environnement, _ = await _environnement_apparie(stack, applique=False)
            revoque = await stack.client.request(
                "DELETE", "/api/pairing/peers", json={"base_url": parametrage.origin}
            )
            assert revoque.status_code == 200, revoque.text

            lues = await stack.client.get(f"/api/environments/{environnement}/versions")

            assert lues.status_code == 409, lues.text
            assert lues.json()["detail"] == "workspace_non_confie"


async def test_un_numero_qui_n_est_pas_une_version_est_refuse_sans_rien_ordonner(
    blank_db: str, tmp_path: Path
) -> None:
    """Course normale : la version a pu disparaître entre l'affichage et le clic."""
    with depot_jetable(tmp_path, VERSIONS) as depot:
        async with open_stack(blank_db, tmp_path, git_test_hosts=(depot.host,)) as stack:
            await _parametrage(stack, depot.url)
            environnement, double = await _environnement_apparie(stack, applique=False)

            ordonne = await stack.client.put(
                f"/api/environments/{environnement}/version", json={"number": 99}
            )

            assert ordonne.status_code == 404, ordonne.text
            assert ordonne.json()["detail"] == "version_inconnue"
            assert double.ordered == []
            assert await _types(stack) == []


async def test_changer_le_workspace_libere_la_version_ordonnee(
    blank_db: str, tmp_path: Path
) -> None:
    """Elle visait le workspace PRÉCÉDENT : la laisser ferait servir le dépôt d'un autre.

    Et l'event existe parce que personne ne l'a demandée : sans trace, on chercherait qui
    a retiré la version.
    """
    with depot_jetable(tmp_path, VERSIONS) as depot:
        async with open_stack(blank_db, tmp_path, git_test_hosts=(depot.host,)) as stack:
            await _parametrage(stack, depot.url)
            environnement, _ = await _environnement_apparie(stack, applique=False)
            await stack.client.put(f"/api/environments/{environnement}/version", json={"number": 2})

            retire = await _place(stack, environnement, None)
            apres = await stack.client.get(f"/api/environments/{environnement}/version")

            assert retire.status_code == 200, retire.text
            assert apres.status_code == 404, apres.text
            assert apres.json()["detail"] == "aucune_version_ordonnee"
            assert await _types(stack) == [
                VERSION_ORDERED_EVENT,
                VERSION_REFUSED_EVENT,
                VERSION_RELEASED_EVENT,
            ]


async def test_un_depot_injoignable_est_refuse_en_nommant_ce_que_git_a_dit(
    blank_db: str, tmp_path: Path
) -> None:
    """« Injoignable », « identifiants » et « dépôt inexistant » n'appellent pas le même geste."""
    with depot_jetable(tmp_path, VERSIONS) as depot:
        # Le même hôte, un dépôt qui n'y existe pas : l'adresse passe la validation, et
        # c'est git qui refuse — exactement le cas qu'on veut voir traverser.
        absent = f"http://{depot.host}/proprio/inexistant.git"
        async with open_stack(blank_db, tmp_path, git_test_hosts=(depot.host,)) as stack:
            await _parametrage(stack, absent)
            environnement, _ = await _environnement_apparie(stack, applique=False)

            lues = await stack.client.get(f"/api/environments/{environnement}/versions")

            assert lues.status_code == 422, lues.text
            assert lues.json()["detail"]["code"] == "depot_illisible"
            assert lues.json()["detail"]["reason"]


@pytest.mark.parametrize("chemin", ["/versions", "/version"])
async def test_les_routes_d_administration_exigent_une_session(
    blank_db: str, tmp_path: Path, chemin: str
) -> None:
    """Fail closed : le portillon n'ouvre que la liste blanche des chemins signés."""
    async with open_stack(blank_db, tmp_path) as stack:
        sans_session = stack.anonymous()

        refuse = await sans_session.get(
            f"/api/environments/{'0' * 8}-0000-0000-0000-{'0' * 12}{chemin}"
        )

        assert refuse.status_code == 401, refuse.text
