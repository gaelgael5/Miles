from __future__ import annotations

import re
from pathlib import Path

from miles.reference.labels import country_name, resolve_label
from miles.reference.model import validate_culture

COUNTRIES_MIGRATION = "0028_referentiel_des_pays.sql"

# La règle de repli des libellés, et ses TROIS branches (story ccd8703c, critère 5).
#
# Elle s'éprouve ici, sans base : c'est une fonction pure au-dessus des données CLDR, et
# c'est là que son erreur serait silencieuse — un libellé faux ne casse rien, il ment.


def _pays(alpha2: str) -> object:
    """La fonction de dérivation telle que le service la passe."""
    return lambda culture: country_name(alpha2, culture)


def test_le_libelle_vient_de_la_culture_du_visiteur_quand_elle_est_active() -> None:
    libelle = resolve_label(
        culture="fr-FR",
        active_cultures=frozenset({"fr-FR", "en-US"}),
        derive=_pays("DE"),  # type: ignore[arg-type]
        fallback="DEU",
    )

    assert libelle == "Allemagne"


def test_une_culture_non_active_ne_sert_pas_et_le_repli_est_en_us() -> None:
    """Une culture désactivée ne sert plus rien (cadrage, 15/10/2026).

    La lire ici contournerait la décision prise sur l'écran des cultures : c'est bien
    « Germany » qu'un visiteur doit lire, pas « Allemagne ».
    """
    libelle = resolve_label(
        culture="fr-FR",
        active_cultures=frozenset({"en-US"}),
        derive=_pays("DE"),  # type: ignore[arg-type]
        fallback="DEU",
    )

    assert libelle == "Germany"


def test_une_culture_que_cldr_ne_connait_pas_retombe_sur_le_repli() -> None:
    """Le référentiel des cultures porte des codes que CLDR ne couvre pas — `apc`, mesuré.

    C'est un cas NORMAL, pas une panne : la lecture de la liste entière ne doit pas échouer
    parce qu'une culture active n'a pas de données CLDR.
    """
    assert country_name("DE", "apc") is None

    libelle = resolve_label(
        culture="apc",
        active_cultures=frozenset({"apc", "en-US"}),
        derive=_pays("DE"),  # type: ignore[arg-type]
        fallback="DEU",
    )

    assert libelle == "Germany"


def test_sans_aucun_libelle_c_est_le_slug_qui_est_rendu() -> None:
    """Troisième branche : le slug est toujours vrai, et jamais un vide.

    `QQ` n'est pas un territoire de CLDR — mesuré, là où `ZZ` en est un (« Unknown
    Region »). Un écran qui afficherait une case vide ferait croire à une donnée manquante.

    Cette branche est INATTEIGNABLE avec la liste ISO d'aujourd'hui (voir le test de
    complétude ci-dessous), et elle est gardée quand même : une révision de l'ISO peut
    ajouter un pays avant que CLDR ne le nomme, et le second référentiel donné — les
    fuseaux horaires — réemploiera cette même règle avec d'autres données.
    """
    assert country_name("QQ", "fr-FR") is None

    libelle = resolve_label(
        culture="fr-FR",
        active_cultures=frozenset({"fr-FR", "en-US"}),
        derive=_pays("QQ"),  # type: ignore[arg-type]
        fallback="QQQ",
    )

    assert libelle == "QQQ"


def test_les_249_pays_du_referentiel_ont_tous_un_libelle_de_repli() -> None:
    """La donnée est complète, et c'est ce qui rend le repli sur le slug exceptionnel.

    Mesuré sur la migration elle-même plutôt que sur une liste recopiée ici : c'est elle
    qui sera jouée. Ce test rougira le jour où une révision de l'ISO ajoutera un pays que
    CLDR ne nomme pas encore — et ce jour-là, l'écran affichera son code, ce qui est la
    bonne conduite mais mérite d'être su.
    """
    sql = (Path(__file__).resolve().parents[1] / "migrations" / COUNTRIES_MIGRATION).read_text(
        encoding="utf-8"
    )
    paires = re.findall(r"\('([A-Z]{3})', '([A-Z]{2})'\)", sql)

    assert len(paires) == 249
    assert [alpha3 for alpha3, alpha2 in paires if not country_name(alpha2, "en-US")] == []


def test_aucune_culture_demandee_donne_le_repli() -> None:
    """L'appelant n'a pas dit sa culture : on ne devine pas, on prend le repli garanti."""
    libelle = resolve_label(
        culture=None,
        active_cultures=frozenset({"fr-FR", "en-US"}),
        derive=_pays("FR"),  # type: ignore[arg-type]
        fallback="FRA",
    )

    assert libelle == "France"


def test_le_repli_n_est_jamais_consulte_deux_fois() -> None:
    """`en-US` demandée ET active : une seule tentative, pas deux.

    Sans la garde, la liste des candidats porterait deux fois le même code et chaque
    libellé manquant coûterait une lecture CLDR de plus — 249 fois par affichage.
    """
    appels: list[str] = []

    def derive(culture: str) -> str | None:
        appels.append(culture)
        return None

    assert (
        resolve_label(
            culture="en-US",
            active_cultures=frozenset({"en-US"}),
            derive=derive,
            fallback="ZZZ",
        )
        == "ZZZ"
    )
    assert appels == ["en-US"]


def test_les_libelles_suivent_la_culture_pour_plusieurs_pays() -> None:
    """Jeu d'essai DISCRIMINANT : trois pays dont les noms diffèrent d'une langue à l'autre.

    « France » se dit pareil en anglais : seul, il ne prouverait pas que la culture est
    prise en compte.
    """
    attendus = {
        "DE": ("Allemagne", "Germany"),
        "ES": ("Espagne", "Spain"),
        "GB": ("Royaume-Uni", "United Kingdom"),
    }
    for alpha2, (en_francais, en_anglais) in attendus.items():
        assert country_name(alpha2, "fr-FR") == en_francais
        assert country_name(alpha2, "en-US") == en_anglais


def test_un_libelle_vide_est_ecarte_comme_un_libelle_absent() -> None:
    """Le contrat de la fonction : jamais un vide, quoi que rende `derive`.

    Mesuré le 30/10/2026 : CLDR ne rend de chaîne vide ni pour les 249 territoires, ni pour
    les 312 zones canoniques. Cette branche est donc éprouvée par un `derive` SYNTHÉTIQUE —
    c'est le contrat de la fonction qui est en jeu, pas un comportement de CLDR, et
    `resolve_label` accepte n'importe quelle fonction de dérivation.
    """
    appels: list[str] = []

    def derive(culture: str) -> str | None:
        appels.append(culture)
        return "" if culture == "fr-FR" else "Germany"

    libelle = resolve_label(
        culture="fr-FR",
        active_cultures=frozenset({"fr-FR", "en-US"}),
        derive=derive,
        fallback="DEU",
    )

    # Le vide ne passe pas pour un libellé : on continue jusqu'au repli.
    assert libelle == "Germany"
    assert appels == ["fr-FR", "en-US"]


def test_la_culture_demandee_est_validee_pour_elle_meme() -> None:
    """La validation de la culture, éprouvée SEULE — et il faut le faire exprès.

    Son effet est doublé : `_locale` capture déjà ce que Babel refuse, donc le
    comportement visible (« une culture mal formée donne le repli ») reste juste même sans
    elle. Ce qu'elle apporte en plus ne se voit pas dans une réponse : elle empêche une
    chaîne arbitraire de servir de CLÉ au cache de locales — 512 entrées de rebut en
    chasseraient les vraies — et de partir dans un analyseur qui n'a pas à servir de garde
    d'entrée. Sans ce test, la retirer ne ferait rougir personne.
    """
    assert validate_culture("fr-FR") == "fr-FR"
    assert validate_culture("fr") == "fr"
    assert validate_culture("zh-Hant-TW") == "zh-Hant-TW"
    # Lues comme « pas de culture », jamais transmises telles quelles.
    assert validate_culture(None) is None
    assert validate_culture("../../etc/passwd") is None
    assert validate_culture("fr_FR") is None
    assert validate_culture("") is None
    assert validate_culture("a" * 200) is None
