from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict

from miles.reference.activation import EmptyChangeError, UnknownSlugsError
from miles.reference.holidays import HolidayDay, UnknownToEngineError
from miles.reference.model import SLUG_RE, Country, validate_culture
from miles.reference.service import CountriesService

# Le référentiel des pays, section Global du portail. Le préfixe est `/api/countries` et
# non `/api/referentials` : le mot « référentiel » désigne déjà trois autres choses dans ce
# produit — les référentiels d'objets ingérés, les référentiels de mapping de git, les
# storages — et une route qui le reprendrait se confondrait avec eux.
#
# Réservées à l'administrateur tant que les rôles n'existent pas : la passerelle refuse
# toute autre session, et aucune de ces routes n'est publique.
router = APIRouter(prefix="/api/countries")


def countries_service(request: Request) -> CountriesService:
    service: CountriesService = request.app.state.countries
    return service


Service = Annotated[CountriesService, Depends(countries_service)]


class CountryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    alpha2: str
    # Dérivé de CLDR à la lecture, dans la culture demandée. Jamais stocké, donc jamais
    # périmé : activer une culture de plus change ce champ sans aucune migration.
    label: str
    active: bool
    # Le pays a-t-il un fichier de règles de jours fériés ? Dans la liste, pour que
    # l'association se voie sans déplier les 249 pays un par un.
    has_holidays: bool


class HolidayDayOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # La date LÉGALE et le jour CHÔMÉ, toujours les deux. `observed` est rendu même quand
    # il égale `date` : un écran qui doit tester l'égalité pour savoir quoi écrire finit
    # par écrire « — » là où la réponse est « le même jour ».
    date: dt.date
    observed: dt.date
    name: str
    free: bool
    shifted: bool


class HolidaysOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Le nom du pays chez calendarium : c'est la clé d'interrogation du moteur, et elle ne
    # ressemble pas toujours au libellé affiché (`United_States`, `Macedonia_FYRO`).
    country: str
    # L'URL BRUTE, telle que la base la porte, et la page navigable qui s'en dérive. Les
    # deux, parce que c'est la première qui est vérifiable et la seconde qu'on clique.
    source_url: str
    page_url: str
    start: dt.date
    end: dt.date
    days: list[HolidayDayOut]


class ActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slugs: list[str]
    active: bool


class ActivationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changed: list[str]


def _out(country: Country) -> CountryOut:
    return CountryOut(
        slug=country.slug,
        alpha2=country.alpha2,
        label=country.label,
        active=country.active,
        has_holidays=country.has_holidays,
    )


def _day_out(day: HolidayDay) -> HolidayDayOut:
    return HolidayDayOut(
        date=day.date,
        observed=day.observed,
        name=day.name,
        free=day.free,
        shifted=day.shifted,
    )


@router.get("", response_model=list[CountryOut])
async def list_countries(
    service: Service,
    culture: Annotated[str | None, Query(max_length=40)] = None,
    only_active: bool = False,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> list[CountryOut]:
    """Les pays, avec leur libellé dans la culture demandée.

    `only_active` existe pour les écrans qui PROPOSENT un pays : ils n'en proposeront pas
    249. `q` filtre sur le code et sur le libellé dérivé — filtrer sur le seul code
    obligerait à connaître « DEU » pour trouver l'Allemagne.

    La culture est validée avant d'aller lire CLDR avec elle. Une forme inattendue est lue
    comme « pas de culture » : l'écran affiche alors les libellés de repli, ce qui vaut
    mieux qu'une liste vide pour un paramètre mal formé.
    """
    pays = await service.resolve_list(
        culture=validate_culture(culture), only_active=only_active, search=q
    )
    return [_out(p) for p in pays]


@router.get("/{slug}/holidays", response_model=HolidaysOut)
async def country_holidays(slug: str, service: Service) -> HolidaysOut | JSONResponse:
    """Le fichier de règles d'un pays et les jours qu'il produit sur 12 mois.

    Le slug est validé AVANT d'entrer dans une requête : il vient d'un chemin d'URL. Une
    forme inattendue rend le même refus qu'un pays sans règles — elle ne désigne aucun
    pays, et distinguer les deux renseignerait sur ce que la base contient.

    `aucune_regle` n'est pas une panne : calendarium couvre 111 pays vérifiés là où le
    référentiel en porte 249. L'écran l'affiche, et c'est pour ça que la liste rend
    `has_holidays` — il n'appelle cette route que pour les pays qui en ont.
    """
    if not SLUG_RE.match(slug):
        return _error({"field": "slug"}, status.HTTP_404_NOT_FOUND, "aucune_regle")
    try:
        holidays = await service.resolve_holidays(slug)
    except UnknownToEngineError as exc:
        # La base désigne un fichier que le paquet installé ne porte pas : incohérence de
        # VERSION, pas saisie fautive. Nommée, parce que le geste est d'aller regarder la
        # version de calendarium — un 500 n'enverrait nulle part.
        return _error({"country": str(exc)}, status.HTTP_409_CONFLICT, "regles_indisponibles")
    if holidays is None:
        return _error({"field": "slug"}, status.HTTP_404_NOT_FOUND, "aucune_regle")
    return HolidaysOut(
        country=holidays.rule.country,
        source_url=holidays.rule.source_url,
        page_url=holidays.rule.page_url,
        start=holidays.start,
        end=holidays.end,
        days=[_day_out(day) for day in holidays.days],
    )


@router.post("/activation", response_model=ActivationResult)
async def set_activation(
    body: ActivationRequest, request: Request, service: Service
) -> ActivationResult | JSONResponse:
    """Active ou désactive exactement la sélection reçue. Rend ce qui a réellement changé.

    Un seul geste pour les deux sens, comme pour les cultures : l'écran envoie une
    sélection et un sens, et la moitié appliquée serait un état que personne n'a demandé.
    """
    try:
        changed = await service.resolve_set_active(request_author(request), body.slugs, body.active)
    except UnknownSlugsError as exc:
        # Les slugs fautifs sont NOMMÉS : ils viennent d'une saisie d'écran, et lui cacher
        # lesquels l'obligerait à tout retenter.
        return _error({"field": "slugs", "unknown": list(exc.slugs)})
    except EmptyChangeError:
        return _error({"field": "slugs"})
    return ActivationResult(changed=changed)


def _error(
    detail: object,
    code: int = status.HTTP_422_UNPROCESSABLE_CONTENT,
    reason: str | None = None,
) -> JSONResponse:
    """Un refus. `reason` nomme le motif quand il y en a plusieurs à distinguer.

    Le corps garde la forme `{"detail": ...}` des refus déjà servis par ce routeur : en
    changer pour les nouvelles routes aurait obligé l'écran à lire deux formes.
    """
    contenu: dict[str, object] = {"detail": detail}
    if reason is not None:
        contenu["reason"] = reason
    return JSONResponse(status_code=code, content=contenu)
