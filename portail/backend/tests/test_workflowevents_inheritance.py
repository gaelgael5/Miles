"""L'héritage entre types d'event : le `$ref`, sa redirection, et le refus des cycles.

Tout est éprouvé ici SANS dépôt ni forge — le module ne prend qu'un lecteur. C'est la
leçon du 17/11/2026, et elle vaut doublement pour ce sujet : le cycle est le cas qu'on ne
veut pas découvrir en campagne, parce que sans garde il ne rend pas un refus, il fait
tomber le processus (`RecursionError`, mesuré le 22/11/2026 sur `jsonschema 4.26.0`).

La forme de l'héritage est celle du standard et celle que le dépôt écrit déjà :
`allOf: [{$ref: miles:/shared/colis}]`, l'`$id` posé par le système. Décision du
22/11/2026, feature `c8f3d8da`.
"""

from __future__ import annotations

import pytest
import yaml

from miles.datamodels.grammar import ModelGrammarError
from miles.datamodels.layout import model_path
from miles.workflowevents.inheritance import (
    MAX_DEPTH,
    Reader,
    ancestors,
    ancestry,
    cycle_problems,
    parents_of,
    with_parent,
)

COLIS = ("shared", "colis")
LIVRE = ("domains", "livraison")  # portée « domains » volontairement absurde : voir plus bas


def _model(name: str, *, parent: tuple[str, str] | None = None, **rest: object) -> str:
    """Un modèle tel que Miles l'écrit : l'`$id` posé par le système, puis le corps."""
    body: dict[str, object] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"miles:/shared/{name}",
        "title": name,
        "type": "object",
        "properties": {},
        **rest,
    }
    text = yaml.safe_dump(body, allow_unicode=True, sort_keys=False)
    return with_parent(text, parent) if parent is not None else text


def _branch(files: dict[tuple[str, str], str]) -> Reader:
    paths = {model_path(*model): text for model, text in files.items()}

    async def read(path: str) -> str | None:
        return paths.get(path)

    return read


class TestCeDontUnPayloadHerite:
    def test_un_allOf_de_tete_designe_le_parent(self) -> None:
        text = _model("colis_livre", parent=COLIS)

        assert parents_of(text) == (COLIS,)
        # Et la forme écrite est bien celle du standard, avec l'`$id` du parent.
        assert yaml.safe_load(text)["allOf"] == [{"$ref": "miles:/shared/colis"}]

    def test_un_ref_sous_une_propriete_n_est_PAS_un_parent(self) -> None:
        """La distinction du standard : composer un schéma, ou typer un champ.

        Sans elle, un modèle qui porte un champ `Dossier: {$ref: …}` se lirait comme
        héritant du dossier, et l'écran afficherait un héritage que personne n'a posé.
        """
        text = _model(
            "demande", properties={"Dossier": {"$ref": "miles:/shared/dossier"}}
        )

        assert parents_of(text) == ()

    def test_un_document_illisible_n_herite_de_rien_et_ne_leve_pas(self) -> None:
        # Tolérance volontaire, comme `references_in` : un fichier retouché hors de Miles
        # doit encore pouvoir s'afficher, et c'est la validation de branche qui le nomme.
        assert parents_of("{ ceci n'est pas du YAML") == ()
        assert parents_of("") == ()


class TestRedirigerLHeritage:
    def test_poser_un_parent_sur_un_modele_qui_n_en_avait_pas(self) -> None:
        text = with_parent(_model("colis_livre"), COLIS)

        data = yaml.safe_load(text)
        assert data["allOf"] == [{"$ref": "miles:/shared/colis"}]
        # L'en-tête du système survit, et l'`allOf` se pose juste après le `type` : la
        # redirection doit se lire comme un diff d'une ligne.
        assert list(data) == ["$schema", "$id", "title", "type", "allOf", "properties"]

    def test_rediriger_remplace_le_parent_et_ne_touche_à_rien_d_autre(self) -> None:
        avant = _model("colis_livre", parent=COLIS, properties={"Canal": {"type": "string"}})

        apres = with_parent(avant, ("livraison", "tournee"))

        assert parents_of(apres) == (("livraison", "tournee"),)
        assert yaml.safe_load(apres)["properties"] == {"Canal": {"type": "string"}}
        assert yaml.safe_load(apres)["$id"] == "miles:/shared/colis_livre"

    def test_revenir_a_l_event_de_base_retire_le_ref_et_l_allOf(self) -> None:
        """L'event de base n'a pas de `$ref` : le moteur applique sa racine d'office.

        Laisser un `allOf: []` derrière serait un document que le méta-schéma refuse
        (`allOf` exige au moins un élément).
        """
        apres = with_parent(_model("colis_livre", parent=COLIS), None)

        assert parents_of(apres) == ()
        assert "allOf" not in yaml.safe_load(apres)

    def test_ce_qui_n_est_pas_un_heritage_dans_l_allOf_est_CONSERVÉ(self) -> None:
        # Discriminant : une contrainte écrite à la main dans l'`allOf` ne désigne aucun
        # modèle, et la perdre changerait le sens du document sans qu'on l'ait demandé.
        avant = _model("colis_livre", allOf=[{"required": ["Canal"]}])

        apres = with_parent(avant, COLIS)

        assert yaml.safe_load(apres)["allOf"] == [
            {"$ref": "miles:/shared/colis"},
            {"required": ["Canal"]},
        ]

    def test_un_document_qui_n_est_pas_un_objet_est_refusé(self) -> None:
        with pytest.raises(ModelGrammarError):
            with_parent("- une liste\n", COLIS)


class TestRemonterLesParents:
    async def test_une_chaine_de_trois_est_rendue_en_entier(self) -> None:
        read = _branch(
            {
                ("shared", "a"): _model("a"),
                ("shared", "b"): _model("b", parent=("shared", "a")),
                ("shared", "c"): _model("c", parent=("shared", "b")),
            }
        )

        assert await ancestors(read, [("shared", "c")]) == (
            ("shared", "c"),
            ("shared", "b"),
            ("shared", "a"),
        )

    async def test_un_parent_absent_n_arrete_pas_la_remontee(self) -> None:
        """Ce n'est pas à ce module de refuser : `check_references` nomme déjà le modèle
        manquant, et deux refus pour un manquement enverraient corriger deux fois."""
        read = _branch({("shared", "b"): _model("b", parent=("shared", "absent"))})

        assert await ancestors(read, [("shared", "b")]) == (("shared", "b"), ("shared", "absent"))

    async def test_un_cycle_ne_fait_pas_boucler_la_remontee(self) -> None:
        # Sans la mémoire des modèles déjà vus, ce test ne finirait jamais.
        read = _branch(
            {
                ("shared", "a"): _model("a", parent=("shared", "b")),
                ("shared", "b"): _model("b", parent=("shared", "a")),
            }
        )

        assert await ancestors(read, [("shared", "a")]) == (("shared", "a"), ("shared", "b"))

    async def test_plus_profond_que_la_borne_rend_None(self) -> None:
        """Rendre `None` plutôt qu'une ascendance tronquée : une ascendance qu'on ne sait
        pas parcourir ne permet d'affirmer ni les clés, ni l'absence de parent fermé."""
        chaine = {
            ("shared", f"n{i}"): _model(f"n{i}", parent=("shared", f"n{i + 1}"))
            for i in range(MAX_DEPTH + 2)
        }

        assert await ancestors(_branch(chaine), [("shared", "n0")]) is None


class TestLeRefusDesCycles:
    async def test_un_modele_qui_se_designe_lui_meme(self) -> None:
        read = _branch({("shared", "a"): _model("a")})

        problems = await cycle_problems(read, ("shared", "a"), ("shared", "a"))

        assert [(p.path, p.code) for p in problems] == [("allOf", "heritage_recursif")]
        # Le refus NOMME la boucle : c'est ce qui dit quoi corriger.
        assert problems[0].detail == "shared/a → shared/a → shared/a"

    async def test_un_cycle_direct_entre_deux_events(self) -> None:
        # `b` hérite de `a` ; faire hériter `a` de `b` ferme la boucle.
        read = _branch(
            {
                ("shared", "a"): _model("a"),
                ("shared", "b"): _model("b", parent=("shared", "a")),
            }
        )

        problems = await cycle_problems(read, ("shared", "a"), ("shared", "b"))

        assert [p.code for p in problems] == ["heritage_recursif"]

    async def test_un_cycle_INDIRECT_par_un_troisieme(self) -> None:
        """`a → b → c`, puis rediriger `a` sur `c` : c'est le cas que seule une remontée
        complète voit, et c'est celui qui part en `RecursionError` sans garde."""
        read = _branch(
            {
                ("shared", "a"): _model("a"),
                ("shared", "b"): _model("b", parent=("shared", "a")),
                ("shared", "c"): _model("c", parent=("shared", "b")),
            }
        )

        problems = await cycle_problems(read, ("shared", "a"), ("shared", "c"))

        assert [p.code for p in problems] == ["heritage_recursif"]

    async def test_un_heritage_qui_ne_boucle_pas_est_admis(self) -> None:
        # Le cas nominal, sans lequel les trois précédents prouveraient seulement qu'on
        # refuse tout.
        read = _branch(
            {
                ("shared", "a"): _model("a"),
                ("shared", "b"): _model("b", parent=("shared", "a")),
            }
        )

        assert await cycle_problems(read, ("shared", "c"), ("shared", "b")) == []

    async def test_une_ascendance_trop_profonde_est_refusée_en_nommant_la_borne(self) -> None:
        chaine = {
            ("shared", f"n{i}"): _model(f"n{i}", parent=("shared", f"n{i + 1}"))
            for i in range(MAX_DEPTH + 2)
        }

        problems = await cycle_problems(_branch(chaine), ("shared", "x"), ("shared", "n0"))

        assert [(p.code, p.detail) for p in problems] == [
            ("heritage_trop_profond", str(MAX_DEPTH))
        ]


class TestCeQueLAscendanceApporte:
    async def test_les_proprietes_des_parents_sont_rendues(self) -> None:
        """Elles comptent : `UNIQUE (Montant)` est valide sur un event qui tient `Montant`
        de son parent, parce que le moteur valide le schéma COMPOSÉ."""
        read = _branch(
            {
                ("shared", "a"): _model("a", properties={"Montant": {"type": "integer"}}),
                ("shared", "b"): _model(
                    "b", parent=("shared", "a"), properties={"Canal": {"type": "string"}}
                ),
            }
        )

        above = await ancestry(read, [("shared", "a")])

        assert above is not None
        assert above.models == (("shared", "a"),)
        assert above.properties == frozenset({"Montant"})
        assert above.problems == ()

    async def test_un_parent_FERMÉ_est_un_manquement_qui_le_nomme(self) -> None:
        """Le payload composé est ce que le moteur valide : un parent fermé refuse les
        propriétés du socle, donc l'enfant est insatisfiable sans qu'aucun des deux
        fichiers ne paraisse faux."""
        read = _branch(
            {("shared", "a"): _model("a", additionalProperties=False)},
        )

        above = await ancestry(read, [("shared", "a")])

        assert above is not None
        assert [(p.path, p.code, p.detail) for p in above.problems] == [
            ("allOf", "schema_ferme", "shared/a : additionalProperties")
        ]

    async def test_un_parent_qui_redeclare_le_socle_est_un_manquement(self) -> None:
        read = _branch(
            {("shared", "a"): _model("a", properties={"ExternalId": {"type": "integer"}})}
        )

        above = await ancestry(read, [("shared", "a")])

        assert above is not None
        assert [(p.code, p.detail) for p in above.problems] == [
            ("propriete_du_socle", "shared/a : ExternalId")
        ]

    async def test_un_parent_illisible_est_nommé_avant_qu_on_ecrive_l_enfant(self) -> None:
        read = _branch({("shared", "a"): "- pas un objet\n"})

        above = await ancestry(read, [("shared", "a")])

        assert above is not None
        assert [(p.code, p.detail) for p in above.problems] == [
            ("parent_non_conforme", "shared/a")
        ]

    async def test_une_ascendance_trop_profonde_rend_None(self) -> None:
        chaine = {
            ("shared", f"n{i}"): _model(f"n{i}", parent=("shared", f"n{i + 1}"))
            for i in range(MAX_DEPTH + 2)
        }

        assert await ancestry(_branch(chaine), [("shared", "n0")]) is None

    async def test_aucun_parent_rend_une_ascendance_vide(self) -> None:
        # Le cas « rien trouvé », celui qu'on oublie : un event qui dérive de l'event de
        # base n'a aucun parent, et ce n'est pas une erreur.
        above = await ancestry(_branch({}), [])

        assert above is not None
        assert (above.models, above.properties, above.problems) == ((), frozenset(), ())
