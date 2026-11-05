from __future__ import annotations

from miles_socle.parametrage.models import ModelUsage, PathEntry, paths_of, usage_of


def _keys(schema: object, path: str) -> tuple[str, ...] | None:
    return next(e.keys for e in paths_of(schema) if e.path == path)


def test_un_chemin_porte_les_noms_de_proprietes_traverses() -> None:
    """Ce qui permet d'en faire une expression jsonb : `objet #>> '{Contact,Phone}'`."""
    schema = {
        "type": "object",
        "properties": {
            "Contact": {
                "type": "object",
                "properties": {"Phone": {"type": "string"}},
            }
        },
    }

    assert _keys(schema, "$.Contact.Phone") == ("Contact", "Phone")


def test_un_ref_interne_est_suivi_et_les_noms_restent_ceux_du_chemin() -> None:
    """Le modèle réel de Gael : `Contact` est un `$ref` vers `#/$defs/Contact`.

    Les noms traversés sont ceux du DOCUMENT, pas ceux de la définition pointée : c'est
    le chemin dans le jsonb stocké qui compte, et il ne connaît pas les `$defs`.
    """
    schema = {
        "type": "object",
        "properties": {"Contact": {"$ref": "#/$defs/Contact"}},
        "$defs": {
            "Contact": {"type": "object", "properties": {"Email": {"type": "string"}}},
        },
    }

    assert _keys(schema, "$.Contact.Email") == ("Contact", "Email")


def test_un_chemin_qui_traverse_un_tableau_ne_porte_aucun_nom() -> None:
    """None, et pas un tuple partiel : il n'existe aucun chemin jsonb scalaire qui y mène.

    C'est ce qui interdit d'en faire une colonne projetée, et l'interdiction est posée
    ici plutôt que chez chaque consommateur.
    """
    schema = {
        "type": "object",
        "properties": {
            "Carriers": {
                "type": "array",
                "items": {"type": "object", "properties": {"Name": {"type": "string"}}},
            }
        },
    }

    assert _keys(schema, "$.Carriers") == ("Carriers",)
    assert _keys(schema, "$.Carriers[0]") is None
    assert _keys(schema, "$.Carriers[0].Name") is None


def test_une_propriete_de_nom_exotique_est_citee_et_garde_son_nom_brut() -> None:
    schema = {"type": "object", "properties": {"code postal": {"type": "string"}}}

    assert paths_of(schema) == [
        PathEntry('$["code postal"]', "string", "", ("code postal",)),
    ]


def test_l_utilite_des_champs_se_lit_a_la_racine_du_modele() -> None:
    schema = {
        "type": "object",
        "properties": {"Id": {"type": "string"}},
        "x-miles": {"key": ["$.Id"], "columns": ["$.Id", "$.Name"]},
    }

    assert usage_of(schema) == ModelUsage(key=("$.Id",), columns=("$.Id", "$.Name"))


def test_un_modele_sans_declaration_n_en_porte_aucune() -> None:
    assert usage_of({"type": "object"}) == ModelUsage()
    assert usage_of(True) == ModelUsage()


def test_une_declaration_retouchee_a_la_main_hors_forme_est_ignoree() -> None:
    # Le fichier s'édite aussi dans le YAML et hors de Miles : une valeur qui n'est pas
    # une liste de chemins ne doit pas faire échouer la lecture de toute la version.
    schema = {"type": "object", "x-miles": {"key": "$.Id", "columns": [3, "$.Name"]}}

    assert usage_of(schema) == ModelUsage(key=(), columns=("$.Name",))
