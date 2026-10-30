from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from tests.integration.work_stack import EDITION, Forge, open_work_forge

pytestmark = pytest.mark.integration

TRADS = "/api/workspaces/retrait/trads"
KEYS = f"{TRADS}/accueil/keys"
CULTURES = "/api/workspaces/retrait/cultures"
# `en-US` est la culture par défaut du workspace de test ; `ar-MA` s'écrit de droite à
# gauche, et c'est elle qui rend les critères de sens d'écriture mesurables.
DEFAULT = "en-US"


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        await _context(opened)
        yield opened


async def _context(forge: Forge, name: str = "accueil") -> None:
    created = await forge.client.post(
        TRADS, json={"name": name, "label": f"Libellé {name}"}, timeout=120
    )
    assert created.status_code == 201, created.text


async def _cultures(forge: Forge, *codes: str) -> None:
    for code in codes:
        added = await forge.client.post(CULTURES, json={"culture": code})
        assert added.status_code == 200, added.text


async def _add(
    forge: Forge, slug: str = "titre", values: dict[str, str | None] | None = None
) -> httpx.Response:
    body = {"slug": slug, "values": values if values is not None else {DEFAULT: "Hello"}}
    return await forge.client.post(KEYS, json=body, timeout=120)


async def _file(forge: Forge, culture: str, context: str = "accueil") -> str | None:
    return await forge.file(f"trads/{context}/{culture}.yaml")


async def _keys(forge: Forge, **params: object) -> dict[str, object]:
    got = await forge.client.get(KEYS, params=params, timeout=120)
    assert got.status_code == 200, got.text
    return dict(got.json())


# --- Critères 1, 2, 3 : ajouter une clé ---


async def test_a_key_appears_in_the_table_and_in_the_default_culture_file(forge: Forge) -> None:
    added = await _add(forge, "titre", {DEFAULT: "Hello"})

    assert added.status_code == 201, added.text
    page = await _keys(forge)
    assert page["keys"] == [{"slug": "titre", "values": {DEFAULT: "Hello"}}]
    assert "titre: Hello" in (await _file(forge, DEFAULT) or "")


async def test_a_key_without_a_value_in_the_default_culture_is_refused(forge: Forge) -> None:
    await _cultures(forge, "ar-MA")

    refused = await _add(forge, "titre", {"ar-MA": "مرحبا"})

    assert refused.status_code == 422
    assert refused.json()["detail"] == {
        "code": "valeur_par_defaut_obligatoire",
        "culture": DEFAULT,
    }
    assert (await _keys(forge))["keys"] == []


async def test_an_empty_string_in_the_default_culture_is_refused_too(forge: Forge) -> None:
    refused = await _add(forge, "titre", {DEFAULT: ""})

    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "valeur_par_defaut_obligatoire"


async def test_a_slug_already_taken_in_the_context_is_refused_and_named(forge: Forge) -> None:
    await _add(forge, "titre")

    again = await _add(forge, "titre", {DEFAULT: "Autre"})

    assert again.status_code == 409
    assert again.json()["detail"] == {"code": "slug_pris", "slug": "titre"}
    # Et la valeur d'origine est intacte : un refus n'écrase rien.
    assert (await _keys(forge))["keys"][0]["values"][DEFAULT] == "Hello"


@pytest.mark.parametrize("hostile", ["Titre", "mon titre", "a.b", "..", ""])
async def test_an_invalid_slug_is_refused(forge: Forge, hostile: str) -> None:
    refused = await _add(forge, hostile)

    assert refused.status_code == 422
    assert refused.json()["detail"] == {"field": "slug", "reason": "forme"}


async def test_the_same_slug_may_live_in_two_different_contexts(forge: Forge) -> None:
    await _context(forge, "erreurs")
    await _add(forge, "titre")

    elsewhere = await forge.client.post(
        f"{TRADS}/erreurs/keys", json={"slug": "titre", "values": {DEFAULT: "Error"}}, timeout=120
    )

    assert elsewhere.status_code == 201, elsewhere.text


# --- Critère 4 : seule la culture touchée est réécrite ---


async def test_saving_one_culture_rewrites_only_its_own_file(forge: Forge) -> None:
    """Vérifiable au diff : c'est lui qui rend le dispositif relisible."""
    await _cultures(forge, "ar-MA", "fr-FR")
    await _add(forge, "titre", {DEFAULT: "Hello", "fr-FR": "Bonjour"})
    before_default = await _file(forge, DEFAULT)
    before_fr = await _file(forge, "fr-FR")

    saved = await forge.client.put(
        f"{KEYS}/titre", json={"values": {"ar-MA": "مرحبا"}}, timeout=120
    )

    assert saved.status_code == 200, saved.text
    assert await _file(forge, DEFAULT) == before_default
    assert await _file(forge, "fr-FR") == before_fr
    assert "مرحبا" in (await _file(forge, "ar-MA") or "")


async def test_a_culture_absent_from_the_body_is_left_untouched(forge: Forge) -> None:
    await _cultures(forge, "ar-MA")
    await _add(forge, "titre", {DEFAULT: "Hello", "ar-MA": "مرحبا"})

    await forge.client.put(f"{KEYS}/titre", json={"values": {DEFAULT: "Hi"}}, timeout=120)

    page = await _keys(forge)
    assert page["keys"][0]["values"] == {DEFAULT: "Hi", "ar-MA": "مرحبا"}


# --- Critères 5 et 6 : vider une valeur ---


async def test_emptying_an_additional_value_removes_its_line_from_that_file(
    forge: Forge,
) -> None:
    await _cultures(forge, "ar-MA")
    await _add(forge, "titre", {DEFAULT: "Hello", "ar-MA": "مرحبا"})

    emptied = await forge.client.put(f"{KEYS}/titre", json={"values": {"ar-MA": None}}, timeout=120)

    assert emptied.status_code == 200, emptied.text
    # La ligne DISPARAÎT plutôt que de rester vide, et la clé redevient non couverte.
    assert "titre" not in (await _file(forge, "ar-MA") or "")
    page = await _keys(forge)
    assert page["keys"][0]["values"] == {DEFAULT: "Hello"}
    assert (await _keys(forge, untranslated="ar-MA"))["total"] == 1


async def test_emptying_the_default_value_is_refused(forge: Forge) -> None:
    await _add(forge, "titre")

    refused = await forge.client.put(f"{KEYS}/titre", json={"values": {DEFAULT: None}}, timeout=120)

    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "valeur_par_defaut_obligatoire"
    assert (await _keys(forge))["keys"][0]["values"][DEFAULT] == "Hello"


async def test_a_culture_outside_the_workspace_is_refused_and_named(forge: Forge) -> None:
    """Écrire un fichier pour une culture hors des réglages créerait une langue que
    l'écran ne montre pas, et personne ne la retrouverait."""
    await _add(forge, "titre")

    refused = await forge.client.put(
        f"{KEYS}/titre", json={"values": {"th-TH": "สวัสดี"}}, timeout=120
    )

    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "culture_hors_workspace", "culture": "th-TH"}


# --- Critères 12 et 13 : les caractères et l'aller-retour ---


async def test_a_value_with_special_characters_survives_the_round_trip(forge: Forge) -> None:
    await _cultures(forge, "ar-MA", "th-TH")
    difficile = {
        DEFAULT: "Line 1\nLine 2 with \"quotes\" and 'apostrophes'",
        "ar-MA": "مرحبا‏ بالعالم",
        "th-TH": "สวัสดีครับ\tมี tab",
    }

    assert (await _add(forge, "titre", difficile)).status_code == 201

    page = await _keys(forge)
    assert page["keys"][0]["values"] == difficile
    # Et le fichier reste lisible par un humain : les glyphes ne sont pas échappés.
    assert "مرحبا" in (await _file(forge, "ar-MA") or "")


async def test_pasting_a_direction_override_is_refused_and_names_what_was_found(
    forge: Forge,
) -> None:
    refused = await _add(forge, "titre", {DEFAULT: "Hello ‮ world"})

    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert detail["code"] == "direction_forcee"
    assert any("U+202E" in found for found in detail["found"])


async def test_a_simple_direction_mark_is_accepted(forge: Forge) -> None:
    """Un nom de marque latin au milieu d'une phrase arabe en a besoin."""
    await _cultures(forge, "ar-MA")

    added = await _add(forge, "titre", {DEFAULT: "Hello", "ar-MA": "شركة‏ Acme"})

    assert added.status_code == 201, added.text
    assert (await _keys(forge))["keys"][0]["values"]["ar-MA"] == "شركة‏ Acme"


# --- Critères 15 et 16 : renommer et supprimer ---


async def test_renaming_a_slug_moves_it_in_every_culture_file(forge: Forge) -> None:
    await _cultures(forge, "ar-MA")
    await _add(forge, "titre", {DEFAULT: "Hello", "ar-MA": "مرحبا"})

    renamed = await forge.client.post(
        f"{KEYS}/titre/rename", json={"new_slug": "titre-accueil"}, timeout=120
    )

    assert renamed.status_code == 200, renamed.text
    page = await _keys(forge)
    assert page["keys"][0]["slug"] == "titre-accueil"
    assert page["keys"][0]["values"] == {DEFAULT: "Hello", "ar-MA": "مرحبا"}
    assert "titre:" not in (await _file(forge, "ar-MA") or "")


async def test_renaming_onto_an_existing_slug_is_refused(forge: Forge) -> None:
    await _add(forge, "titre")
    await _add(forge, "adieu", {DEFAULT: "Bye"})

    refused = await forge.client.post(
        f"{KEYS}/titre/rename", json={"new_slug": "adieu"}, timeout=120
    )

    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "slug_pris", "slug": "adieu"}
    assert [k["slug"] for k in (await _keys(forge))["keys"]] == ["adieu", "titre"]  # type: ignore[index]


async def test_renaming_an_unknown_key_is_a_named_refusal(forge: Forge) -> None:
    answered = await forge.client.post(
        f"{KEYS}/absente/rename", json={"new_slug": "autre"}, timeout=120
    )

    assert answered.status_code == 409
    assert answered.json()["detail"] == {"code": "cle_inconnue", "slug": "absente"}


async def test_deleting_a_key_removes_it_from_every_culture_file(forge: Forge) -> None:
    await _cultures(forge, "ar-MA")
    await _add(forge, "titre", {DEFAULT: "Hello", "ar-MA": "مرحبا"})
    await _add(forge, "adieu", {DEFAULT: "Bye"})

    removed = await forge.client.delete(f"{KEYS}/titre", timeout=120)

    assert removed.status_code == 200, removed.text
    assert [k["slug"] for k in (await _keys(forge))["keys"]] == ["adieu"]  # type: ignore[index]
    assert "titre" not in (await _file(forge, "ar-MA") or "")
    assert "titre" not in (await _file(forge, DEFAULT) or "")


async def test_deleting_an_unknown_key_is_a_named_refusal(forge: Forge) -> None:
    answered = await forge.client.delete(f"{KEYS}/absente", timeout=120)

    assert (answered.status_code, answered.json()["detail"]["code"]) == (409, "cle_inconnue")


# --- Critère 17 : une culture retirée garde son fichier ---


async def test_a_culture_removed_from_the_workspace_keeps_its_file_and_comes_back(
    forge: Forge,
) -> None:
    await _cultures(forge, "ar-MA")
    await _add(forge, "titre", {DEFAULT: "Hello", "ar-MA": "مرحبا"})

    assert (await forge.client.delete(f"{CULTURES}/ar-MA")).status_code == 200

    # Sa colonne disparaît des valeurs rendues…
    assert (await _keys(forge))["keys"][0]["values"] == {DEFAULT: "Hello"}
    # …son fichier reste dans le dépôt…
    assert "مرحبا" in (await _file(forge, "ar-MA") or "")
    # …et ses valeurs réapparaissent telles quelles si on la remet.
    assert (await forge.client.post(CULTURES, json={"culture": "ar-MA"})).status_code == 200
    assert (await _keys(forge))["keys"][0]["values"]["ar-MA"] == "مرحبا"


# --- Critère 18 : le volume ---


async def test_the_table_is_paged_and_filtered_by_slug(forge: Forge) -> None:
    for i in range(7):
        assert (await _add(forge, f"cle-{i:02d}", {DEFAULT: f"V{i}"})).status_code == 201

    first = await _keys(forge, limit=3)
    second = await _keys(forge, limit=3, offset=3)
    filtered = await _keys(forge, search="cle-0")

    assert [k["slug"] for k in first["keys"]] == ["cle-00", "cle-01", "cle-02"]  # type: ignore[index]
    assert [k["slug"] for k in second["keys"]] == ["cle-03", "cle-04", "cle-05"]  # type: ignore[index]
    # Le total est celui du filtre, pas de la page : l'écran sait combien il en reste.
    assert (first["total"], filtered["total"]) == (7, 7)


async def test_the_untranslated_filter_returns_exactly_the_keys_to_fill(forge: Forge) -> None:
    await _cultures(forge, "ar-MA")
    await _add(forge, "traduite", {DEFAULT: "Hello", "ar-MA": "مرحبا"})
    await _add(forge, "a-traduire", {DEFAULT: "Bye"})

    page = await _keys(forge, untranslated="ar-MA")

    assert [k["slug"] for k in page["keys"]] == ["a-traduire"]  # type: ignore[index]
    assert page["total"] == 1


async def test_the_untranslated_filter_combines_with_the_search(forge: Forge) -> None:
    await _cultures(forge, "ar-MA")
    for slug in ("bouton-valider", "bouton-annuler", "titre"):
        await _add(forge, slug, {DEFAULT: slug})

    page = await _keys(forge, untranslated="ar-MA", search="bouton")

    assert [k["slug"] for k in page["keys"]] == ["bouton-annuler", "bouton-valider"]  # type: ignore[index]


# --- La branche, les droits, le journal ---


async def test_keys_are_those_of_the_branch_being_looked_at(forge: Forge) -> None:
    await _add(forge, "titre")

    on_root = await forge.client.get(KEYS, params={"branch": "atelier"}, timeout=120)

    assert (on_root.status_code, on_root.json()["detail"]) == (409, "contexte_inconnu")


async def test_an_unknown_context_is_a_named_refusal(forge: Forge) -> None:
    answered = await forge.client.get(f"{TRADS}/absent/keys", timeout=120)

    assert (answered.status_code, answered.json()["detail"]) == (409, "contexte_inconnu")


async def test_the_root_branch_refuses_to_be_written(forge: Forge) -> None:
    refused = await forge.client.post(
        KEYS, json={"slug": "titre", "values": {DEFAULT: "Hello"}}, params={"branch": "atelier"}
    )

    assert refused.json()["detail"] == "branche_racine_lecture_seule"


async def test_keys_are_closed_without_a_session(forge: Forge) -> None:
    async with forge.portal.anonymous() as anonymous:
        assert (await anonymous.get(KEYS)).status_code == 401
        assert (await anonymous.post(KEYS, json={"slug": "x", "values": {}})).status_code == 401
        assert (await anonymous.put(f"{KEYS}/x", json={"values": {}})).status_code == 401
        assert (await anonymous.delete(f"{KEYS}/x")).status_code == 401


async def test_each_gesture_is_journaled_with_the_key_and_the_context(forge: Forge) -> None:
    await _add(forge, "titre")
    await forge.client.put(f"{KEYS}/titre", json={"values": {DEFAULT: "Hi"}}, timeout=120)
    await forge.client.post(f"{KEYS}/titre/rename", json={"new_slug": "accroche"}, timeout=120)
    await forge.client.delete(f"{KEYS}/accroche", timeout=120)

    rows = await forge.portal.pool.fetch(
        "SELECT type, properties FROM events WHERE type LIKE 'trads_key.%' ORDER BY written_at"
    )
    journaled = [(r["type"], _properties(r["properties"])) for r in rows]

    assert [t for t, _ in journaled] == [
        "trads_key.saved",
        "trads_key.saved",
        "trads_key.renamed",
        "trads_key.deleted",
    ]
    assert journaled[0][1]["new"] is True
    assert journaled[1][1]["new"] is False
    assert journaled[2][1]["new_key"] == "accroche"
    assert all(p["context"] == "accueil" for _, p in journaled)
    assert all(p["branch"] == f"back/retrait/{EDITION}" for _, p in journaled)


def _properties(raw: object) -> dict[str, object]:
    # asyncpg rend une colonne `jsonb` en CHAÎNE, pas en dictionnaire (LESSONS.md).
    return json.loads(raw) if isinstance(raw, str) else dict(raw)  # type: ignore[arg-type]
