from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from miles_socle.secrets.crypto import Sealed

from enrolement.pairing.events import (
    GIT_CONNECTIONS_CONFIDED_EVENT,
    GIT_CREDENTIAL_RENEWED_EVENT,
    PAIRING_REVOKED_EVENT,
)
from tests.integration.demandeur_double import (
    RequesterDouble,
    confide_body,
    connexion,
)
from tests.integration.enrolement_stack import (
    EnrolementStack,
    conclut_appariement,
    demande_appariement,
    open_stack,
)

pytestmark = pytest.mark.integration

# Ce que ce module DÉTIENT pour le compte du module de paramétrage (ticket edcf78bc).
#
# Cette campagne éprouve le RÉCEPTEUR. La composition de la charge est celle de la
# doublure, pas celle du module de paramétrage : une faute dans la composition resterait
# invisible d'ici, et c'est la campagne du portail qui l'éprouve — contre une contrepartie
# qui garde les corps reçus. Leçon du 29/10/2026, écrite dans `LESSONS.md`.

# Un credential de test qui ne ressemble à rien d'autre dans la base : on le cherchera
# TEL QUEL dans les réponses d'API et dans le journal, et un jeu d'essai qui porterait une
# valeur banale rendrait cette recherche aveugle.
CREDENTIAL = "pat-de-test-6f2b9c-ne-doit-jamais-sortir"
AUTRE_CREDENTIAL = "pat-renouvele-18ae77-ne-doit-jamais-sortir"


async def _parametrage(stack: EnrolementStack) -> RequesterDouble:
    """Un module de paramétrage apparié pour de vrai, par les deux gestes du protocole."""
    double = RequesterDouble(origin="http://parametrage.test", species="parametrage")
    await demande_appariement(stack, double)
    await conclut_appariement(stack, double)
    return double


async def _environnement(stack: EnrolementStack) -> RequesterDouble:
    """Un environnement apparié pour de vrai, avec son environnement désigné.

    La désignation n'est pas un détail du montage : sans elle, le code n'est pas révélable
    et l'appariement ne se conclut pas (ticket bf2115cd).
    """
    double = RequesterDouble(origin="http://env.test", species="environnement")
    await demande_appariement(stack, double)
    cree = await stack.client.post(
        "/api/environments", json={"label": "Environnement de recette", "slug": "recette"}
    )
    assert cree.status_code == 201, cree.text
    designe = await stack.client.put(
        "/api/pairing/requests/environment",
        params={"base_url": double.origin},
        json={"environment_id": str(cree.json()["id"])},
    )
    assert designe.status_code == 200, designe.text
    await conclut_appariement(stack, double)
    return double


async def _confie(
    stack: EnrolementStack, double: RequesterDouble, revision: int, *connexions: dict[str, Any]
) -> Any:
    return await double.confide(stack.anonymous(), confide_body(revision, connexions))


async def _descelle(pool: asyncpg.Pool, cipher: Any, peer: str, connection_id: str) -> str:
    """Ouvre le credential détenu. La seule lecture SQL de cette campagne, et il en faut une.

    Ce que les routes rendent ne contient JAMAIS le credential — c'est le critère 2 —, donc
    « détient-il la bonne valeur ? » ne peut se vérifier que là où elle est rangée.
    """
    row = await pool.fetchrow(
        "SELECT key_version, nonce, ciphertext FROM confided_git_connection"
        " WHERE peer_base_url = $1 AND id = $2",
        peer,
        connection_id,
    )
    assert row is not None
    scelle = Sealed(row["key_version"], row["nonce"], row["ciphertext"])
    return str(cipher.open(f"{peer}/git-connection/{connection_id}", scelle).reveal())


async def test_les_connexions_confiees_sont_detenues_et_montrees_sans_leur_credential(
    blank_db: str, tmp_path: Path
) -> None:
    """Critères 1 et 2 : disponibles sans ressaisie, et aucun credential nulle part.

    « Sans ressaisie » se mesure ici à ce que l'écran de l'enrôlement montre : la forge, le
    libellé et les workspaces sont arrivés, et personne n'a rien retapé.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        double = await _parametrage(stack)

        recu = await _confie(
            stack,
            double,
            1,
            connexion("yoops", CREDENTIAL, workspaces=[("atelier", "https://github.com/yoops/a")]),
            connexion("autre-forge", AUTRE_CREDENTIAL, base_url="https://github.com"),
        )

        assert recu.status_code == 200, recu.text
        assert recu.json() == {"revision": 1, "held": 2, "destroyed": 0}
        liste = await stack.client.get("/api/pairing/git-connections")
        assert liste.status_code == 200, liste.text
        etat = liste.json()
        assert etat["peer_base_url"] == double.origin
        assert etat["revision"] == 1
        assert [c["id"] for c in etat["connections"]] == ["autre-forge", "yoops"]
        yoops = next(c for c in etat["connections"] if c["id"] == "yoops")
        assert yoops["base_url"] == "https://github.com/yoops"
        assert yoops["workspaces"] == [{"id": "atelier", "repo_url": "https://github.com/yoops/a"}]
        # Le credential n'est pas « masqué » : il n'a aucun champ. C'est la seule façon de
        # ne jamais le divulguer, et un champ masqué finirait par être rempli.
        assert CREDENTIAL not in liste.text
        assert AUTRE_CREDENTIAL not in liste.text
        detail = await stack.client.get("/api/pairing/git-connections/yoops")
        assert detail.status_code == 200, detail.text
        assert detail.json()["credential_readable"] is True
        assert CREDENTIAL not in detail.text
        # Et il est bien celui qui est arrivé : détenu, chiffré, et relisible.
        assert await _descelle(stack.pool, stack.cipher, double.origin, "yoops") == CREDENTIAL


async def test_un_environnement_apparie_ne_peut_pas_confier_de_connexion_git(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 10, premier verrou : l'espèce est vérifiée, et le refus la NOMME.

    L'environnement est APPARIÉ : sa signature est bonne, son origine connue. Ce qui le
    refuse n'est donc ni la clé ni l'origine — c'est ce sous quoi un humain l'a accepté.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        environnement = await _environnement(stack)

        refus = await _confie(stack, environnement, 1, connexion("yoops", CREDENTIAL))

        assert refus.status_code == 409, refus.text
        assert refus.json()["detail"] == "espece_sans_connexions_git"
        detenues = await stack.pool.fetchval("SELECT count(*) FROM confided_git_connection")
        assert detenues == 0


async def test_l_espece_est_tenue_par_la_base_et_pas_seulement_par_le_code(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 10, second verrou : « tenu par un test, parce que c'est la facilité ».

    Le ticket exige que ça tienne au niveau des DONNÉES. Ce test écrit en SQL ce qu'aucune
    route n'offre — une connexion git rattachée à un environnement — et la base refuse.
    Sans lui, retirer la clé étrangère composée ne ferait rougir personne : le refus du
    service, lui, reste vert.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        environnement = await _environnement(stack)

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await stack.pool.execute(
                "INSERT INTO confided_git_connection (peer_base_url, species, id, label,"
                " base_url, key_version, nonce, ciphertext, confided_at)"
                " VALUES ($1, 'parametrage', 'yoops', 'Y', 'https://github.com', 1,"
                " '\\x00'::bytea, '\\x00'::bytea, now())",
                environnement.origin,
            )


async def test_un_credential_remplace_est_detenu_a_la_place_de_l_ancien(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 4 : « l'enrôlement travaille avec le nouveau, et l'ancien n'est plus conservé ».

    Et le renouvellement est DATÉ, ce qui est la seule chose qu'on puisse dire d'un
    credential au-dehors — c'est elle qu'on viendra lire le jour où une lecture de git
    échoue.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        double = await _parametrage(stack)
        await _confie(stack, double, 1, connexion("yoops", CREDENTIAL))
        premier = await stack.client.get("/api/pairing/git-connections/yoops")
        confie_le = premier.json()["connection"]["confided_at"]

        await _confie(stack, double, 2, connexion("yoops", AUTRE_CREDENTIAL))

        assert await _descelle(stack.pool, stack.cipher, double.origin, "yoops") == AUTRE_CREDENTIAL
        apres = await stack.client.get("/api/pairing/git-connections/yoops")
        ligne = apres.json()["connection"]
        assert ligne["renewed_at"] is not None
        # La ligne a été RÉÉCRITE, jamais recréée : `confided_at` n'a pas bougé. Une
        # suppression suivie d'une insertion ferait trouver « connexion inconnue » à une
        # lecture tombant dans l'intervalle, et le diagnostic partirait sur une suppression
        # à la source (critère 5).
        assert ligne["confided_at"] == confie_le
        # L'ancienne valeur n'est conservée nulle part : une seule ligne, un seul chiffré.
        lignes = await stack.pool.fetchval(
            "SELECT count(*) FROM confided_git_connection WHERE id = 'yoops'"
        )
        assert lignes == 1


async def test_une_transmission_qui_ne_change_rien_ne_date_aucun_renouvellement(
    blank_db: str, tmp_path: Path
) -> None:
    """Le pendant du test ci-dessus, et il mord sur la comparaison des credentials.

    Sans elle, chaque transmission daterait un renouvellement qui n'a pas eu lieu — et la
    date qu'on vient lire ne décrirait plus rien.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        double = await _parametrage(stack)
        await _confie(stack, double, 1, connexion("yoops", CREDENTIAL))

        await _confie(stack, double, 2, connexion("yoops", CREDENTIAL, label="Renommée"))

        apres = await stack.client.get("/api/pairing/git-connections/yoops")
        assert apres.json()["connection"]["renewed_at"] is None
        assert apres.json()["connection"]["label"] == "Renommée"


async def test_une_connexion_absente_de_l_etat_est_detruite(blank_db: str, tmp_path: Path) -> None:
    """Critère 9 : supprimée à la source, elle disparaît ici — et la lecture le dit.

    La suppression n'a pas de message à elle : c'est son absence de l'état qui la détruit.
    Le refus de la lecture suivante est un 404 NOMMÉ, distinct du 409 « aucun module de
    paramétrage » : les deux n'appellent pas le même geste.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        double = await _parametrage(stack)
        await _confie(
            stack,
            double,
            1,
            connexion("yoops", CREDENTIAL, workspaces=[("atelier", None)]),
            connexion("ancienne", AUTRE_CREDENTIAL),
        )

        recu = await _confie(stack, double, 2, connexion("yoops", CREDENTIAL))

        assert recu.json() == {"revision": 2, "held": 1, "destroyed": 1}
        disparue = await stack.client.get("/api/pairing/git-connections/ancienne")
        assert disparue.status_code == 404, disparue.text
        assert disparue.json()["detail"] == "connexion_inconnue"
        # Détruite, pas marquée : il ne reste aucune ligne qui porterait encore son
        # credential, et ses workspaces sont partis avec elle.
        assert await stack.pool.fetchval("SELECT count(*) FROM confided_git_connection") == 1
        assert await stack.pool.fetchval("SELECT count(*) FROM confided_git_workspace") == 0


async def test_une_revision_plus_ancienne_est_refusee_sans_rien_ecraser(
    blank_db: str, tmp_path: Path
) -> None:
    """Deux transmissions arrivées dans le désordre : la plus vieille ne gagne pas.

    Le refus dit la révision DÉTENUE — un nombre que l'appelant a lui-même alloué, donc il
    n'apprend rien. Sans elle, il afficherait « confiées » en croyant avoir transmis la
    dernière photo.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        double = await _parametrage(stack)
        await _confie(stack, double, 7, connexion("yoops", AUTRE_CREDENTIAL))

        refus = await _confie(stack, double, 6, connexion("yoops", CREDENTIAL))

        assert refus.status_code == 409, refus.text
        assert refus.json() == {"detail": "revision_depassee", "held_revision": 7}
        assert await _descelle(stack.pool, stack.cipher, double.origin, "yoops") == AUTRE_CREDENTIAL


async def test_aucun_module_de_parametrage_apparie_est_dit_et_non_tu(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 7 : « le dit plutôt que de laisser croire à une panne de la forge ».

    Deux lectures, deux réponses différentes, et c'est la différence qui compte : l'état
    rend un pair NUL — l'écran peut le nommer —, et la lecture d'une connexion précise
    rend un 409 nommé, jamais un 404 qui se lirait « cette connexion a été supprimée ».
    """
    async with open_stack(blank_db, tmp_path) as stack:
        etat = await stack.client.get("/api/pairing/git-connections")

        assert etat.status_code == 200, etat.text
        assert etat.json() == {
            "peer_base_url": None,
            "revision": None,
            "received_at": None,
            "connections": [],
        }
        detail = await stack.client.get("/api/pairing/git-connections/yoops")
        assert detail.status_code == 409, detail.text
        assert detail.json()["detail"] == "aucun_module_de_parametrage"


async def test_la_revocation_detruit_les_connexions_confiees(blank_db: str, tmp_path: Path) -> None:
    """Critère 8 : « détruites, pas marquées inactives » — et le journal dit combien.

    C'est la moitié du critère 4 du ticket ba44914b qui avait été reportée ici, faute de
    quoi que ce soit à détruire à l'époque.
    """
    async with open_stack(blank_db, tmp_path, peer_app=None) as stack:
        double = await _parametrage(stack)
        await _confie(
            stack,
            double,
            1,
            connexion("yoops", CREDENTIAL, workspaces=[("atelier", None)]),
            connexion("autre", AUTRE_CREDENTIAL),
        )

        revoque = await stack.client.delete(
            "/api/pairing/peers", params={"base_url": double.origin}
        )

        assert revoque.status_code == 204, revoque.text
        assert await stack.pool.fetchval("SELECT count(*) FROM confided_git_connection") == 0
        assert await stack.pool.fetchval("SELECT count(*) FROM confided_git_workspace") == 0
        assert await stack.pool.fetchval("SELECT count(*) FROM confided_git_state") == 0
        charge = await _event(stack.pool, PAIRING_REVOKED_EVENT)
        assert charge["git_connections_destroyed"] == 2


async def test_le_journal_nomme_la_transmission_et_le_renouvellement_jamais_le_credential(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 11 : les events portent qui, quoi, et surtout pas la valeur.

    Le journal est lu bien plus largement que la table des connexions confiées : un
    credential qui y passerait, même tronqué, s'y conserverait selon une rétention qui
    n'est pas la nôtre.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        double = await _parametrage(stack)
        await _confie(stack, double, 1, connexion("yoops", CREDENTIAL))

        await _confie(stack, double, 2, connexion("yoops", AUTRE_CREDENTIAL))

        confie = await _event(stack.pool, GIT_CONNECTIONS_CONFIDED_EVENT)
        assert confie["revision"] == 2
        assert confie["connections"] == ["yoops"]
        assert confie["renewed"] == ["yoops"]
        renouvele = await _event(stack.pool, GIT_CREDENTIAL_RENEWED_EVENT)
        assert renouvele["peer_base_url"] == double.origin
        tout = await stack.pool.fetch("SELECT type, properties FROM events")
        ecrit = json.dumps([dict(r) for r in tout], default=str)
        assert CREDENTIAL not in ecrit
        assert AUTRE_CREDENTIAL not in ecrit


async def test_une_charge_malformee_nomme_le_champ_sans_rien_recopier(
    blank_db: str, tmp_path: Path
) -> None:
    """Le refus nomme le CHAMP, jamais la valeur : l'un de ces champs porte un credential."""
    async with open_stack(blank_db, tmp_path) as stack:
        double = await _parametrage(stack)

        refus = await _confie(stack, double, 1, connexion("Majuscules-Interdites", CREDENTIAL))

        assert refus.status_code == 422, refus.text
        assert refus.json()["detail"] == "connection_id"
        assert "Majuscules-Interdites" not in refus.text
        assert await stack.pool.fetchval("SELECT count(*) FROM confided_git_connection") == 0


async def _event(pool: asyncpg.Pool, event_type: str) -> dict[str, Any]:
    """La charge du dernier event de ce type. Les colonnes sont `type` et `written_at`."""
    row = await pool.fetchrow(
        "SELECT properties FROM events WHERE type = $1 ORDER BY written_at DESC LIMIT 1",
        event_type,
    )
    assert row is not None, f"aucun event {event_type}"
    charge: dict[str, Any] = json.loads(row["properties"])
    return charge
