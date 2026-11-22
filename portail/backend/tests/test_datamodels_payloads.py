"""Le payload d'un type d'event n'est pas un modèle d'objet : qui le prend, et pour qui.

Éprouvé SANS dépôt ni forge — le module ne prend qu'un lecteur (leçon du 17/11/2026). Ce
qui compte ici n'est pas qu'un refus sorte, c'est qu'il NOMME le type d'event et son
artefact : sans eux, il faudrait ouvrir chaque périmètre pour savoir où aller le retirer.

Jeux d'essai discriminants : deux périmètres, deux modèles dont un seul est un payload, et
un modèle désigné par deux types d'event — pas un seul modèle et un seul event, qui aurait
laissé passer à peu près n'importe quelle implémentation.
"""

from __future__ import annotations

from miles.datamodels.layout import model_path
from miles.datamodels.payloads import claimed, event_payloads
from miles.datamodels.usages import Reader
from miles.workflowevents.dsl import EventType, fragment_path, render

COLIS = ("shared", "colis")
SITE = ("shared", "site")
DEMANDE = ("domains/livraison", "demande")


def _model(scope: str, name: str) -> str:
    return (
        "$schema: https://json-schema.org/draft/2020-12/schema\n"
        f"$id: miles:/{'shared' if scope == 'shared' else scope}/{name}\n"
        f"title: {name.title()}\ntype: object\nproperties: {{}}\n"
    )


def _branch(files: dict[str, str]) -> tuple[Reader, list[str]]:
    async def read(path: str) -> str | None:
        return files.get(path)

    return read, sorted(files)


# Deux périmètres : le transverse prend `colis` pour payload, le domaine prend `demande`.
# `site` n'est le payload de personne, et c'est lui qui prouve que la règle discrimine.
BRANCHE = {
    model_path("shared", "colis"): _model("shared", "colis"),
    model_path("shared", "site"): _model("shared", "site"),
    model_path("livraison", "demande"): _model("domains/livraison", "demande"),
    fragment_path("shared"): render(
        "shared", [EventType("colis_recu", "Colis reçu", ("shared", "colis"))]
    ),
    fragment_path("livraison"): render(
        "livraison", [EventType("demande_soumise", "Demande soumise", ("livraison", "demande"))]
    ),
}


async def test_chaque_payload_est_nomme_avec_son_type_d_event_et_son_artefact() -> None:
    read, paths = _branch(BRANCHE)

    assert await event_payloads(read, paths) == {
        ("shared", "colis"): "colis_recu · shared/shared.wf",
        ("livraison", "demande"): "demande_soumise · domains/livraison/livraison.wf",
    }


async def test_un_modele_qu_aucun_DEFINE_EVENT_ne_designe_reste_libre() -> None:
    """Le cas qui doit continuer de passer : un modèle d'objet ordinaire (critère 5)."""
    read, paths = _branch(BRANCHE)

    assert claimed(await event_payloads(read, paths), "shared/site") is None


async def test_le_refus_nomme_le_type_d_event_et_le_perimetre_qui_le_declare() -> None:
    read, paths = _branch(BRANCHE)
    payloads = await event_payloads(read, paths)

    assert claimed(payloads, "shared/colis") == "colis_recu · shared/shared.wf"
    assert (
        claimed(payloads, "livraison/demande") == "demande_soumise · domains/livraison/livraison.wf"
    )


async def test_un_payload_partage_par_deux_types_d_event_ne_montre_que_le_premier() -> None:
    """Rien n'interdit le partage — seul le NOM d'un type est unique —, et le refus n'a
    qu'un endroit à montrer : montrer les deux ferait chercher lequel retirer."""
    read, paths = _branch(
        {
            model_path("shared", "colis"): _model("shared", "colis"),
            fragment_path("shared"): render(
                "shared",
                [
                    EventType("colis_recu", "Colis reçu", ("shared", "colis")),
                    EventType("colis_rendu", "Colis rendu", ("shared", "colis")),
                ],
            ),
        }
    )

    assert claimed(await event_payloads(read, paths), "shared/colis") == (
        "colis_recu · shared/shared.wf"
    )


async def test_une_declaration_supprimee_rend_le_modele_a_nouveau_LIBRE() -> None:
    """Critère 6 : l'état n'est pas un aller simple. C'est l'usage qui décide, pas le
    nom ni le dossier — donc retirer le `DEFINE EVENT` suffit, sans rien déplacer."""
    sans_declaration = {k: v for k, v in BRANCHE.items() if k != fragment_path("shared")}
    read, paths = _branch(sans_declaration)

    assert claimed(await event_payloads(read, paths), "shared/colis") is None


async def test_un_champ_qui_ne_designe_pas_un_modele_ne_porte_pas_ce_refus_la() -> None:
    """Son propre refus le dit déjà (`modele_inconnu`) : deux refus pour un seul
    manquement enverraient corriger deux fois la même chose."""
    read, paths = _branch(BRANCHE)

    assert claimed(await event_payloads(read, paths), "pas-un-modele") is None
    assert claimed(await event_payloads(read, paths), "") is None


async def test_un_artefact_illisible_ne_fait_inventer_aucun_payload() -> None:
    """Un périmètre retouché hors de Miles : on ne devine pas ce qu'il désignait, et la
    validation de la branche le nomme déjà sous son propre chemin."""
    read, paths = _branch({**BRANCHE, fragment_path("shared"): "ceci n'est pas du DSL"})

    assert await event_payloads(read, paths) == {
        ("livraison", "demande"): "demande_soumise · domains/livraison/livraison.wf"
    }
