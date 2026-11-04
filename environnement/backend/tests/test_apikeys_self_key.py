"""La clé que le back-office détient pour lui-même : ses cinq branches.

Sur des doublures, parce que ce qui se décide ici se décide en Python : émettre ou
retrouver, refuser une clé révoquée, réémettre quand la ligne a disparu, et réaligner les
octrois SEULEMENT s'ils ont changé. Le dispositif réel — le chiffrement, l'usage déclaré
qui interdit la suppression, la révocation en base — s'éprouve sur une vraie base, dans la
campagne d'intégration : aucune doublure ne dit ce que le magasin de secrets fait vraiment.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import pytest
from miles_socle.apikeys.model import key_digest
from miles_socle.events.model import EventAuthor
from miles_socle.secrets.model import Secret, SecretNotFoundError

from environnement.apikeys.self_key import (
    SELF_KEY_LABEL,
    SELF_KEY_SLUG,
    SELF_KEY_TYPE,
    SelfKeyRevokedError,
    SelfKeyService,
)
from environnement.apikeys.store import StoredKey

AUTEUR = EventAuthor("local", "admin")
INSTANT = datetime(2026, 11, 4, 9, tzinfo=UTC)


@dataclass
class _Info:
    id: str
    prefix: str


class _Keys:
    """Le service des clés, doublé : il enregistre les gestes qu'on lui demande."""

    def __init__(self, sources: tuple[str, ...] = ("comptes-pudo", "sites-pudo")) -> None:
        self.sources = sources
        self.emises: list[tuple[str, tuple[str, ...]]] = []
        self.octrois: list[tuple[str, tuple[str, ...]]] = []
        self.revoquees: list[str] = []
        self.panne = False

    async def resolve_declared_sources(self) -> tuple[str, ...]:
        return self.sources

    async def resolve_issue(
        self, author: EventAuthor, label: str, sources: tuple[str, ...]
    ) -> tuple[_Info, str]:
        self.emises.append((label, sources))
        rang = len(self.emises)
        return _Info(id=f"k{rang}", prefix="mlk_abcd"), f"mlk_valeur_{rang}"

    async def resolve_set_grants(
        self, author: EventAuthor, key_id: str, sources: tuple[str, ...]
    ) -> None:
        self.octrois.append((key_id, sources))

    async def resolve_revoke(self, author: EventAuthor, key_id: str) -> tuple[None, bool]:
        self.revoquees.append(key_id)
        return None, False


class _Secrets:
    """Le magasin, doublé. `range` est la valeur rangée, nulle quand il n'y a rien."""

    def __init__(self, range: str | None = None) -> None:
        self.range = range
        self.creations: list[tuple[str, str]] = []
        self.remplacements: list[str] = []
        self.rattachements: list[str] = []
        self.panne = False

    async def resolve_secret(self, slug: str, expected_type: str | None = None) -> Secret:
        assert (slug, expected_type) == (SELF_KEY_SLUG, SELF_KEY_TYPE)
        if self.range is None:
            raise SecretNotFoundError(slug)
        return Secret(self.range)

    async def resolve_create(
        self, author: EventAuthor, slug: str, label: str, secret_type: str, value: str
    ) -> None:
        if self.panne:
            raise RuntimeError("magasin indisponible")
        self.creations.append((slug, secret_type))
        self.range = value

    async def resolve_replace_value(self, author: EventAuthor, slug: str, value: str) -> None:
        if self.panne:
            raise RuntimeError("magasin indisponible")
        self.remplacements.append(slug)
        self.range = value


class _Pool:
    """Le pool n'est employé que pour le rattachement de l'usage, qu'on observe ici."""

    def __init__(self, secrets: _Secrets) -> None:
        self.secrets = secrets

    def acquire(self) -> Any:
        return _Acquired(self.secrets)


class _Acquired:
    def __init__(self, secrets: _Secrets) -> None:
        self.secrets = secrets

    async def __aenter__(self) -> _Acquired:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def transaction(self) -> Any:
        return _Rien()

    async def fetchrow(self, query: str, *args: Any) -> Any:
        """Le verrou que pose la déclaration d'usage : il lit le TYPE du secret rangé."""
        assert "FROM secrets WHERE slug" in query
        return None if self.secrets.range is None else {"secret_type": SELF_KEY_TYPE}

    async def execute(self, query: str, *args: Any) -> str:
        if "secret_usages" in query:
            self.secrets.rattachements.append(str(args[0]))
        return "OK"


class _Rien:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: object) -> None:
        return None


def _stored(raw: str, sources: tuple[str, ...], *, revoquee: bool = False) -> StoredKey:
    return StoredKey(
        id="k1",
        label=SELF_KEY_LABEL,
        prefix="mlk_abcd",
        digest=key_digest(raw),
        sources=sources,
        created_at=INSTANT,
        created_by_directory="local",
        created_by_subject="admin",
        revoked_at=INSTANT if revoquee else None,
        last_used_at=None,
    )


def _service(keys: _Keys, secrets: _Secrets) -> SelfKeyService:
    # Les types concrets sont ceux de la production ; les doublures en tiennent le
    # contrat. mypy ne vérifie que `src`, donc rien ne se perd à les passer ici.
    return SelfKeyService(pool=_Pool(secrets), keys=keys, secrets=secrets)  # type: ignore[arg-type]


def _retrouve(monkeypatch: pytest.MonkeyPatch, stored: StoredKey | None) -> None:
    async def _lu(pool: object, digest: bytes) -> StoredKey | None:
        if stored is None or stored.digest != digest:
            return None
        return stored

    monkeypatch.setattr("environnement.apikeys.self_key.db_key_of_digest", _lu)


class TestPremiereDemande:
    async def test_une_cle_est_emise_rangee_et_son_usage_declare(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        keys, secrets = _Keys(), _Secrets(range=None)
        _retrouve(monkeypatch, None)

        valeur = await _service(keys, secrets).resolve_usable(AUTEUR)

        assert valeur.reveal() == "mlk_valeur_1"
        # Octroyée sur TOUTES les sources déclarées : le back-office doit pouvoir
        # essayer n'importe quel point d'entrée de la version servie.
        assert keys.emises == [(SELF_KEY_LABEL, ("comptes-pudo", "sites-pudo"))]
        assert secrets.creations == [(SELF_KEY_SLUG, SELF_KEY_TYPE)]

    async def test_une_stack_sans_version_servie_emet_une_cle_sans_octroi(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sans version, aucune source n'est déclarée. La clé existe et n'ouvre rien —
        et c'est juste : il n'y a aucun point d'entrée à essayer."""
        keys, secrets = _Keys(sources=()), _Secrets(range=None)
        _retrouve(monkeypatch, None)

        await _service(keys, secrets).resolve_usable(AUTEUR)

        assert keys.emises == [(SELF_KEY_LABEL, ())]


class TestDemandesSuivantes:
    async def test_la_meme_cle_est_rendue_sans_rien_emettre(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le critère qui interdit qu'un second essai crée une seconde clé."""
        keys, secrets = _Keys(), _Secrets(range="mlk_deja_la")
        _retrouve(monkeypatch, _stored("mlk_deja_la", ("comptes-pudo", "sites-pudo")))

        valeur = await _service(keys, secrets).resolve_usable(AUTEUR)

        assert valeur.reveal() == "mlk_deja_la"
        assert keys.emises == []
        assert secrets.creations == [] and secrets.remplacements == []

    async def test_une_valeur_rangee_sans_ligne_correspondante_fait_REEMETTRE(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La base a été recréée sous un secret conservé. Rendre la valeur rangée donnerait
        un justificatif refusé, et personne ne saurait pourquoi."""
        keys, secrets = _Keys(), _Secrets(range="mlk_orpheline")
        _retrouve(monkeypatch, None)

        valeur = await _service(keys, secrets).resolve_usable(AUTEUR)

        assert valeur.reveal() == "mlk_valeur_1"
        # REMPLACÉE et non recréée : le slug est déjà pris, et le magasin le refuserait.
        assert secrets.remplacements == [SELF_KEY_SLUG]
        assert secrets.creations == []


class TestRevocation:
    async def test_une_cle_revoquee_est_DITE_et_rien_n_est_reemis(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La révocation est un geste délibéré : la reprendre en silence l'annulerait."""
        keys, secrets = _Keys(), _Secrets(range="mlk_revoquee")
        _retrouve(monkeypatch, _stored("mlk_revoquee", ("comptes-pudo",), revoquee=True))

        with pytest.raises(SelfKeyRevokedError) as refus:
            await _service(keys, secrets).resolve_usable(AUTEUR)

        assert refus.value.key_id == "k1"
        assert keys.emises == []

    async def test_une_reemission_EXPLICITE_remplace_la_valeur(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        keys, secrets = _Keys(), _Secrets(range="mlk_revoquee")
        _retrouve(monkeypatch, _stored("mlk_revoquee", ("comptes-pudo",), revoquee=True))

        valeur = await _service(keys, secrets).resolve_reissue(AUTEUR)

        assert valeur.reveal() == "mlk_valeur_1"
        assert secrets.remplacements == [SELF_KEY_SLUG]


class TestOctrois:
    async def test_les_octrois_sont_realignes_quand_la_version_servie_a_change(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        keys = _Keys(sources=("comptes-pudo", "magasins-import"))
        secrets = _Secrets(range="mlk_deja_la")
        _retrouve(monkeypatch, _stored("mlk_deja_la", ("comptes-pudo",)))

        await _service(keys, secrets).resolve_usable(AUTEUR)

        assert keys.octrois == [("k1", ("comptes-pudo", "magasins-import"))]

    async def test_des_octrois_INCHANGES_ne_sont_pas_reecrits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """C'est le DELTA qui parle : réécrire à chaque essai écrirait un event par clic,
        et un journal qui répète le même geste ne se lit plus."""
        keys = _Keys(sources=("sites-pudo", "comptes-pudo"))
        secrets = _Secrets(range="mlk_deja_la")
        # Les mêmes sources, dans un AUTRE ordre : l'ordre n'est pas une différence.
        _retrouve(monkeypatch, _stored("mlk_deja_la", ("comptes-pudo", "sites-pudo")))

        await _service(keys, secrets).resolve_usable(AUTEUR)

        assert keys.octrois == []


class TestPanneDuMagasin:
    async def test_une_valeur_non_rangee_fait_REVOQUER_la_cle_tout_juste_emise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sinon un justificatif actif traînerait, que personne ne détient."""
        keys, secrets = _Keys(), _Secrets(range=None)
        secrets.panne = True
        _retrouve(monkeypatch, None)

        with pytest.raises(RuntimeError):
            await _service(keys, secrets).resolve_usable(AUTEUR)

        assert keys.revoquees == ["k1"]


class TestCeQuiNeFuitPas:
    def test_la_valeur_ne_se_lit_pas_dans_la_representation_du_secret(self) -> None:
        """Première barrière contre la fuite en journal : le type lui-même se masque.
        La seconde — aucun journal ne la porte — s'éprouve sur une vraie base."""
        porte = Secret("mlk_valeur_1")

        assert "mlk_valeur_1" not in f"{porte!r}"
        assert "mlk_valeur_1" not in str(porte)
        assert porte.reveal() == "mlk_valeur_1"


def test_le_libelle_de_la_cle_dit_d_ou_vient_le_depot() -> None:
    """Il s'affiche dans le journal des appels : un essai depuis l'écran ne doit pas se
    lire comme le dépôt d'un partenaire."""
    assert "Back-office" in SELF_KEY_LABEL
    # Et il ne porte pas de valeur : ce libellé voyage dans la table des ingestions.
    assert "mlk_" not in SELF_KEY_LABEL


def test_remplacer_un_champ_du_service_ne_le_rend_pas_mutable() -> None:
    """Gelé comme les autres services du produit : on ne le reconfigure pas en vol."""
    keys, secrets = _Keys(), _Secrets()
    service = _service(keys, secrets)

    autre = replace(service, keys=_Keys())  # type: ignore[arg-type]

    assert autre is not service
