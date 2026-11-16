"""Ce qui DÉSIGNE un modèle, lu des déclarations de la branche et de rien d'autre.

La question vient de Gael, le 16/11/2026 : « sur les models (event et objets), la façon
d'identifier qui fait quoi m'échappe. » Jusqu'au 14/11/2026 le RANGEMENT y répondait ;
depuis, c'est la déclaration qui désigne — d'où ces tests, qui éprouvent la lecture
croisée plutôt que l'affichage.

Les jeux d'essai sont DISCRIMINANTS : un modèle sans aucun usage, un modèle à deux usages
de nature différente, une désignation dont la cible manque, et un modèle désigné par un
autre modèle. Un seul modèle désigné par un seul storage aurait laissé passer à peu près
n'importe quelle implémentation.
"""

from __future__ import annotations

from miles.chains.layout import ChainDoc, StepDoc, chain_path, chain_text
from miles.datamodels.layout import ModelEntry, entry_of, model_path
from miles.datamodels.usages import (
    CHAIN_STEP,
    EVENT_TYPE,
    MODEL,
    SOURCE,
    STORAGE,
    Listing,
    read_listing,
)
from miles.sources.layout import Entry, EntryModes, SourceDoc, source_path, source_text
from miles.storages.layout import StorageDoc, storage_path, storage_text
from miles.workflowevents.dsl import EventType, fragment_path, render


def _model(name: str, *, refs: tuple[str, ...] = ()) -> str:
    lines = [
        "$schema: https://json-schema.org/draft/2020-12/schema",
        f"$id: miles:/shared/{name}",
        f"title: {name.title()}",
        "type: object",
        "properties:",
        "  Id:",
        "    type: string",
    ]
    for rank, ref in enumerate(refs):
        lines += [f"  Lie{rank}:", f"    $ref: {ref}"]
    return "\n".join(lines) + "\n"


def _storage(name: str, model: str) -> str:
    return storage_text(StorageDoc(name, name.title(), model, ("$.Id",), (), ()))


def _source(name: str, model: str) -> str:
    entry = Entry("web", model, "colis-import", EntryModes(True, False, False), "", False, 100)
    return source_text(SourceDoc(name, name.title(), "sites", (entry,)))


def _chain(slug: str, *, source: str | None, destination: str | None) -> str:
    step = StepDoc("vers-pivot", None, source, destination)
    return chain_text(ChainDoc(slug, slug.title(), (step,)))


async def _listing(files: dict[str, str]) -> Listing:
    """La lecture sur un dépôt en mémoire : ce module ne demande qu'un lecteur de fichier."""

    async def read(path: str) -> str | None:
        return files.get(path)

    paths = sorted(files)
    models = [
        (ModelEntry(entry.scope, entry.name, entry.path, entry.name.title(), 1), files[path])
        for path in paths
        if (entry := entry_of(path)) is not None
    ]
    return await read_listing(read, paths, models)


async def test_un_modele_que_rien_ne_designe_le_dit_sans_que_ce_soit_une_anomalie() -> None:
    listing = await _listing({model_path("shared", "orphelin"): _model("orphelin")})

    assert [(m.entry.name, m.usages) for m in listing.models] == [("orphelin", ())]
    assert listing.broken == ()


async def test_un_modele_sert_a_deux_choses_de_nature_differente_et_les_montre_toutes_deux() -> (
    None
):
    """Le cas que la liste séparée interdisait : un modèle payload d'un type d'event ET
    stocké par un storage. C'est le renversement du 14/11/2026 qui l'autorise."""
    listing = await _listing(
        {
            model_path("shared", "colis"): _model("colis"),
            fragment_path("shared"): render(
                "shared", [EventType("colis_recu", "Colis reçu", ("shared", "colis"))]
            ),
            storage_path("sites"): _storage("sites", "shared/colis"),
        }
    )

    usages = listing.models[0].usages
    assert [(u.kind, u.name, u.label) for u in usages] == [
        (EVENT_TYPE, "colis_recu", "Colis reçu"),
        (STORAGE, "sites", "Sites"),
    ]
    assert [u.path for u in usages] == ["shared/shared.wf", "storages/sites.yaml"]


async def test_un_type_d_event_est_nomme_lui_meme_pas_seulement_son_artefact() -> None:
    """Critère 3 : c'est le TYPE qu'on cherche, pas le périmètre qui le porte."""
    listing = await _listing(
        {
            model_path("shared", "colis"): _model("colis"),
            fragment_path("shared"): render(
                "shared",
                [
                    EventType("colis_recu", "Colis reçu", ("shared", "colis")),
                    EventType("colis_rendu", "Colis rendu", ("shared", "colis")),
                ],
            ),
        }
    )

    assert [u.name for u in listing.models[0].usages] == ["colis_recu", "colis_rendu"]


async def test_un_modele_designe_par_un_autre_modele_le_sait_et_pas_l_inverse() -> None:
    listing = await _listing(
        {
            model_path("shared", "adresse"): _model("adresse"),
            model_path("shared", "personne"): _model("personne", refs=("miles:/shared/adresse",)),
        }
    )

    by_name = {m.entry.name: m.usages for m in listing.models}
    assert [(u.kind, u.name) for u in by_name["adresse"]] == [(MODEL, "shared/personne")]
    assert by_name["personne"] == ()


async def test_un_modele_recursif_n_est_pas_son_propre_usage() -> None:
    # Sans cette garde, un schéma qui se désigne lui-même se présenterait comme servant
    # à quelque chose d'autre que lui-même.
    listing = await _listing(
        {model_path("shared", "noeud"): _model("noeud", refs=("miles:/shared/noeud",))}
    )

    assert listing.models[0].usages == ()


async def test_une_designation_dont_la_cible_manque_est_rendue_au_lieu_d_etre_tue() -> None:
    """Critère 5 : la référence cassée se voit ici, et non seulement au blocage d'une
    version. Le storage désigne un modèle que la branche n'a pas."""
    listing = await _listing(
        {
            model_path("shared", "colis"): _model("colis"),
            storage_path("sites"): _storage("sites", "shared/absent"),
            fragment_path("shared"): render(
                "shared", [EventType("parti", "Parti", ("shared", "ailleurs"))]
            ),
        }
    )

    assert listing.models[0].usages == ()
    assert [(d.kind, d.name, d.target) for d in listing.broken] == [
        (EVENT_TYPE, "parti", ("shared", "ailleurs")),
        (STORAGE, "sites", ("shared", "absent")),
    ]


async def test_une_entree_de_source_dit_de_laquelle_il_s_agit() -> None:
    listing = await _listing(
        {
            model_path("shared", "compte"): _model("compte"),
            source_path("comptes"): _source("comptes", "shared/compte"),
        }
    )

    usage = listing.models[0].usages[0]
    assert (usage.kind, usage.name, usage.part) == (SOURCE, "comptes", "entrees[0]")


async def test_une_etape_de_chaine_qui_lit_et_produit_le_meme_modele_ne_le_dit_qu_une_fois() -> (
    None
):
    listing = await _listing(
        {
            model_path("shared", "pivot"): _model("pivot"),
            chain_path("comptes-import"): _chain(
                "comptes-import",
                source="miles:/shared/pivot",
                destination="miles:/shared/pivot",
            ),
        }
    )

    usages = listing.models[0].usages
    assert [(u.kind, u.name, u.part) for u in usages] == [
        (CHAIN_STEP, "comptes-import", "vers-pivot")
    ]


async def test_une_chaine_sans_modele_declare_n_invente_aucun_usage() -> None:
    # Une chaîne écrite avant le 24/10/2026 n'en porte aucun : une absence ne se
    # transforme pas en usage supposé.
    listing = await _listing(
        {
            model_path("shared", "pivot"): _model("pivot"),
            chain_path("vieille"): _chain("vieille", source=None, destination=None),
        }
    )

    assert listing.models[0].usages == ()


async def test_un_artefact_illisible_ne_fait_inventer_aucun_usage() -> None:
    """On ne devine pas ce qu'un fichier retouché hors de Miles désigne. La validation de
    la branche le nomme, et c'est elle qui refuse d'en figer une version."""
    listing = await _listing(
        {
            model_path("shared", "colis"): _model("colis"),
            fragment_path("shared"): "FRAGMENT NAME shared\n\nDEFINE EVENT (\n",
        }
    )

    assert listing.models[0].usages == ()
    assert listing.broken == ()
